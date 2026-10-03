"""Reviewer (TRD §10, TR-2/TR-3/TR-7): claim extraction → Jev claim
verdicts → faithfulness / min-support / citation-precision → optional
single revision pass.

The scoring math here is the eval gate's core signal (TRD §15), so the
pure functions (`score_review`, `plan_delivery`, verdict→p mapping) carry
Critical-tier unit coverage in tests/graph/test_review.py — everything
I/O-ish (LLM extraction, Jev batches, revision call) is mockable via
`complete_fn` / `engine`, per the LangGraph node-test rule in testing.md.
"""

import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from decisions.engine import EngineProtocol
from prompts.load import load_prompt
from providers.llm import complete
from retrieval.context import count_tokens
from retrieval.expand import ExpandedContext
from schemas.decisions import Answer, Choice, Question

logger = logging.getLogger(__name__)

VERDICT_OPTIONS = ["supported", "partial", "unsupported", "contradicted"]
PARTIAL_CREDIT = 0.5
REVISION_MIN_SUPPORT = 0.5
BATCH_TOKEN_BUDGET = 28_000
_CHUNK_CAP = 2000

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_CITATION_RE = re.compile(r"\[(\d{1,2})\]")
# KI-53: a claim that asserts the sources LACK something ("the sources do
# not say X", "no mention of X in the sources"). Such a claim is verified
# the other way round — the passages are the evidence, and any passage that
# states X contradicts the claim. English phrasings only: the proxy-labelled
# answer sheet is English, and a multilingual absence regex is a separate
# piece of work (the reviewer still flags these via the normal verdict when
# the extractor cites them).
_ABSENCE_CLAIM_RE = re.compile(
    r"""
    (?:
        (?:the\s+)?(?:sources?|passages?|cited\s+sources?|documents?|texts?|
                    provided\s+sources?|retrieved\s+sources?)\s+
        (?:do\s+not|does\s+not|don'?t|did\s+not|didn'?t|fail(?:s)?\s+to|
            lack(?:s)?|omit(?:s)?)
      |
        (?:no|not\s+any|there\s+is\s+no)\s+(?:any\s+)?
        (?:mention|reference|information|details?|data|guidance)\s+
        (?:of|about|regarding|for|on|in|covering|concerning|specific\s+to|
            beyond)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class ExtractedClaim:
    claim_id: str
    text: str
    citation_ids: list[int]
    is_factual: bool


@dataclass
class VerifiedClaim:
    claim: ExtractedClaim
    verdict: str
    p_supported: float
    engine: str


@dataclass(frozen=True)
class ReviewScores:
    faithfulness: float
    min_support: float
    citation_precision: float


@dataclass
class ReviewResult:
    claims: list[VerifiedClaim] = field(default_factory=list)
    scores: ReviewScores | None = None
    revised_text: str | None = None
    diff: str | None = None


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    return match.group(1).strip() if match is not None else stripped


def _p_for_verdict(verdict: str, answer: Answer) -> float:
    if verdict == "supported":
        probability = answer.probabilities.get("supported") if answer.probabilities else None
        if probability is None:
            probability = answer.probability
        return probability if probability is not None else 1.0
    if verdict == "partial":
        return PARTIAL_CREDIT
    return 0.0


def score_review(claims: list[VerifiedClaim], citation_count: int) -> ReviewScores:
    """Faithfulness = (supported + 0.5*partial) / factual claims (TRD §10).
    Zero factual claims (abstention, greeting) scores a perfect 1.0 — an
    answer asserting nothing cannot be unfaithful."""
    factual = [c for c in claims if c.claim.is_factual]
    if not factual:
        return ReviewScores(faithfulness=1.0, min_support=1.0, citation_precision=1.0)
    supported = sum(1 for c in factual if c.verdict == "supported")
    partial = sum(1 for c in factual if c.verdict == "partial")
    faithfulness = (supported + PARTIAL_CREDIT * partial) / len(factual)
    min_support = min(c.p_supported for c in factual)
    pairs = [(claim, n) for claim in factual for n in claim.claim.citation_ids]
    if pairs:
        supporting = sum(1 for claim, _ in pairs if claim.verdict == "supported")
        precision = supporting / len(pairs)
    else:
        precision = 0.0 if citation_count else 1.0
    return ReviewScores(faithfulness, min_support, precision)


def plan_delivery(
    *, mode: str, risk: str, sufficiency_p: float | None, sufficient_threshold: float
) -> str:
    """'hold' (verify before delivery) or 'stream' (deliver, review after)
    per TRD §10's risk-based delivery table. Sufficiency within 0.1 of the
    retry threshold counts as high-risk even when ingress said low."""
    if mode == "deep":
        return "hold"
    if mode == "fast":
        return "stream"
    if risk == "high":
        return "hold"
    if sufficiency_p is not None and abs(sufficiency_p - sufficient_threshold) <= 0.1:
        return "hold"
    return "stream"


def parse_claims(response: str) -> list[ExtractedClaim]:
    try:
        data = json.loads(_strip_fence(response))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    claims: list[ExtractedClaim] = []
    for i, row in enumerate(data):
        if not isinstance(row, dict) or not isinstance(row.get("claim"), str):
            continue
        raw_ids = row.get("citation_ids", [])
        ids = [int(n) for n in raw_ids if isinstance(n, (int, float))]
        claims.append(
            ExtractedClaim(
                claim_id=f"c{i + 1}",
                text=row["claim"],
                citation_ids=sorted({n for n in ids if n >= 1}),
                is_factual=bool(row.get("is_factual", True)),
            )
        )
    return claims


def _citation_only_claim(answer: str) -> ExtractedClaim | None:
    citation_ids = sorted({int(n) for n in _CITATION_RE.findall(answer)})
    if not citation_ids or re.sub(r"[\W_]+", "", _CITATION_RE.sub("", answer)):
        return None
    return ExtractedClaim("c1", answer.strip(), citation_ids, True)


async def extract_claims(
    *, answer: str, small_model: str, complete_fn: Any = complete
) -> list[ExtractedClaim]:
    """Read the claims out of a finished answer.

    temperature=0 (KI-32): this parses an answer into claims, it does not
    write prose, and the claim list is the denominator of the faithfulness
    mean (TRD §10 step 3). Left at the provider default, 4 of 20 fast20 items
    re-split their claims between runs — the same fact asserted with and
    without a citation marker moves the score, not the judging.
    """
    prompt = load_prompt("claim_extraction.md").replace("{answer}", answer)
    response = await complete_fn(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": answer}],
        metadata={"job": "claim_extraction", "role": "claim_extractor"},
        temperature=0,
    )
    return parse_claims(response)


def _claim_question(claim: ExtractedClaim, contexts: list[ExpandedContext]) -> Choice:
    cited: list[str] = []
    for n in claim.citation_ids:
        if 1 <= n <= len(contexts):
            cited.append(f"[{n}] {contexts[n - 1].context_text[:_CHUNK_CAP]}")
    state_text = "\n\n".join(cited) if cited else "(no cited source — uncited claim)"
    return Choice(
        prompt=(
            "Verify one claim against its cited sources. Judge ONLY whether "
            "the sources support the claim: supported (fully), partial "
            "(directionally right but overstated or incomplete), unsupported "
            "(nothing in the sources), or contradicted (sources say the "
            f"opposite).\n\n[Claim]\n{claim.text}\n\n[Cited sources]\n{state_text}"
        ),
        options=VERDICT_OPTIONS,
        criteria="evidence support",
    )


def is_absence_claim(claim: ExtractedClaim) -> bool:
    """Does this claim assert that the sources lack something (KI-53)?"""
    return bool(_ABSENCE_CLAIM_RE.search(claim.text))


def _absence_question(claim: ExtractedClaim, contexts: list[ExpandedContext]) -> Choice:
    """KI-53: verify an absence claim against ALL the passages, not just the
    cited ones — the claimed absence is about the whole evidence, and the
    citation marker on such a sentence is unreliable (the false absences in
    the P1b sheet all cited the passage they summarised, while the missing
    fact sat in a different one). The verdict runs the other way round: a
    passage that states the claimed-missing thing contradicts the claim."""
    passages = _sources_block(contexts) or "(no sources retrieved)"
    return Choice(
        prompt=(
            "Verify one absence claim against the sources. The claim asserts "
            "that the sources do NOT say or contain something. Judge ONLY "
            "that asserted absence: if any source states or contains that "
            "something, the claim is contradicted. If no source states or "
            "contains it, the claim is supported. A source that mentions the "
            "subject while staying silent on the specific thing does not "
            "contradict the claim.\n\n"
            f"[Claim]\n{claim.text}\n\n"
            "[Sources]\n" + passages
        ),
        options=VERDICT_OPTIONS,
        criteria="evidence support",
    )


def _verdict_question(claim: ExtractedClaim, contexts: list[ExpandedContext]) -> Choice:
    """The claim-verdict question for one claim: the absence question when
    the claim asserts a source absence (KI-53), the standard support
    question otherwise. Same call, same options — only the framing and the
    evidence block change."""
    if is_absence_claim(claim):
        return _absence_question(claim, contexts)
    return _claim_question(claim, contexts)


def batch_claims(
    to_verify: list[ExtractedClaim], contexts: list[ExpandedContext]
) -> list[list[ExtractedClaim]]:
    """Split into batches whose question text fits one Jev call (<28K
    tokens, TRD §10 step 2). A single claim larger than the budget gets
    its own batch — truncation already caps each chunk. Token counts are
    measured on the question that will actually be sent (KI-53: an
    absence claim carries every passage, not just the cited ones)."""
    batches: list[list[ExtractedClaim]] = []
    current: list[ExtractedClaim] = []
    current_tokens = 0
    for claim in to_verify:
        tokens = count_tokens(_verdict_question(claim, contexts).prompt)
        if current and current_tokens + tokens > BATCH_TOKEN_BUDGET:
            batches.append(current)
            current, current_tokens = [], 0
        current.append(claim)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


async def verify_claims(
    engine: EngineProtocol,
    *,
    run_id: str,
    claims: list[ExtractedClaim],
    contexts: list[ExpandedContext],
    citation_count: int,
) -> tuple[list[VerifiedClaim], list[Answer]]:
    """Uncited factual claims score unsupported with no Jev call (TRD §10
    step 3); cited factual claims go through batched `claim_verdict`
    Choices. Non-factual claims pass through unscored.

    KI-53: an absence claim ("the sources do not say X") is the one factual
    claim that is checked even without a citation — the passages are its
    evidence, and a false absence is exactly what the citation cannot
    surface. It rides the same batched `decide` call, so an answer without
    absence claims makes exactly the calls it always made."""
    verified: list[VerifiedClaim] = []
    answers: list[Answer] = []
    for claim in claims:
        if not claim.is_factual:
            verified.append(VerifiedClaim(claim, "skipped", 0.0, "n/a"))
        elif not claim.citation_ids and not is_absence_claim(claim):
            verified.append(VerifiedClaim(claim, "unsupported", 0.0, "n/a"))

    to_verify = [
        c for c in claims if c.is_factual and (c.citation_ids or is_absence_claim(c))
    ]
    for batch in batch_claims(to_verify, contexts):
        questions: dict[str, Question] = {
            claim.claim_id: _verdict_question(claim, contexts) for claim in batch
        }
        batch_answers = await engine.decide(
            state={"run_id": run_id, "kind": "claim_verdict"}, questions=questions
        )
        for claim in batch:
            answer = batch_answers.get(claim.claim_id)
            verdict = str(answer.value) if answer is not None else "unsupported"
            if verdict not in VERDICT_OPTIONS:
                verdict = "unsupported"
            p = _p_for_verdict(verdict, answer) if answer is not None else 0.0
            engine_name = answer.engine if answer is not None else "n/a"
            verified.append(VerifiedClaim(claim, verdict, p, engine_name))
            if answer is not None:
                answers.append(answer)

    ordered = {c.claim_id: i for i, c in enumerate(claims)}
    verified.sort(key=lambda v: ordered[v.claim.claim_id])
    return verified, answers


def _flagged(claims: list[VerifiedClaim]) -> list[VerifiedClaim]:
    return [
        c
        for c in claims
        if c.claim.is_factual
        and (c.verdict == "contradicted" or c.p_supported < REVISION_MIN_SUPPORT)
    ]


def _needs_revision(claims: list[VerifiedClaim]) -> bool:
    factual = [c for c in claims if c.claim.is_factual]
    if any(c.verdict == "contradicted" for c in factual):
        return True
    return bool(factual) and min(c.p_supported for c in factual) < REVISION_MIN_SUPPORT


def _sources_block(contexts: list[ExpandedContext]) -> str:
    return "\n\n".join(
        f"[{i + 1}] {context.context_text[:_CHUNK_CAP]}" for i, context in enumerate(contexts)
    )


async def revise_answer(
    *,
    answer: str,
    flagged: list[VerifiedClaim],
    contexts: list[ExpandedContext],
    litellm_model: str,
    complete_fn: Any = complete,
) -> str | None:
    if not flagged:
        return None
    prompt = (
        load_prompt("revision.md")
        .replace("{answer}", answer)
        .replace(
            "{flagged}",
            "\n".join(f"- {c.claim.text} ({c.verdict})" for c in flagged),
        )
        .replace("{sources}", _sources_block(contexts))
    )
    revised = await complete_fn(
        litellm_model=litellm_model,
        messages=[{"role": "system", "content": prompt}],
        metadata={"job": "revision", "role": "rewriter"},
    )
    revised_text = str(revised).strip()
    if not revised_text or revised_text == answer.strip():
        return None
    return revised_text


def make_diff(original: str, revised: str) -> str:
    return "\n".join(
        difflib.unified_diff(original.splitlines(), revised.splitlines(), lineterm="", n=1)
    )


async def review_answer(
    *,
    engine: EngineProtocol,
    run_id: str,
    answer: str,
    contexts: list[ExpandedContext],
    citation_count: int,
    small_model: str,
    litellm_model: str,
    complete_fn: Any = complete,
) -> ReviewResult:
    """Full pipeline: extract → verify → scores → at most one revision
    pass (re-extract + re-verify on the revised text, TRD §10 step 5)."""
    result = ReviewResult()
    citation_only = _citation_only_claim(answer)
    if citation_only is not None:
        unsupported = VerifiedClaim(citation_only, "unsupported", 0.0, "n/a")
        result.claims = [unsupported]
        result.scores = score_review(result.claims, citation_count)
        return result
    claims = await extract_claims(answer=answer, small_model=small_model, complete_fn=complete_fn)
    if not claims:
        return result
    verified, _ = await verify_claims(
        engine,
        run_id=run_id,
        claims=claims,
        contexts=contexts,
        citation_count=citation_count,
    )
    result.claims = verified
    result.scores = score_review(verified, citation_count)
    if not _needs_revision(verified):
        return result
    revised = await revise_answer(
        answer=answer,
        flagged=_flagged(verified),
        contexts=contexts,
        litellm_model=litellm_model,
        complete_fn=complete_fn,
    )
    if revised is None:
        return result
    revised_claims = await extract_claims(
        answer=revised, small_model=small_model, complete_fn=complete_fn
    )
    if revised_claims:
        re_verified, _ = await verify_claims(
            engine,
            run_id=run_id,
            claims=revised_claims,
            contexts=contexts,
            citation_count=citation_count,
        )
        result.claims = re_verified
        result.scores = score_review(re_verified, citation_count)
    result.revised_text = revised
    result.diff = make_diff(answer, revised)
    return result
