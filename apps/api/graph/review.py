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


async def extract_claims(
    *, answer: str, small_model: str, complete_fn: Any = complete
) -> list[ExtractedClaim]:
    prompt = load_prompt("claim_extraction.md").replace("{answer}", answer)
    response = await complete_fn(
        litellm_model=small_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": answer}],
        metadata={"job": "claim_extraction"},
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


def batch_claims(
    factual_cited: list[ExtractedClaim], contexts: list[ExpandedContext]
) -> list[list[ExtractedClaim]]:
    """Split into batches whose question text fits one Jev call (<28K
    tokens, TRD §10 step 2). A single claim larger than the budget gets
    its own batch — truncation already caps each chunk."""
    batches: list[list[ExtractedClaim]] = []
    current: list[ExtractedClaim] = []
    current_tokens = 0
    for claim in factual_cited:
        tokens = count_tokens(_claim_question(claim, contexts).prompt)
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
    Choices. Non-factual claims pass through unscored."""
    verified: list[VerifiedClaim] = []
    answers: list[Answer] = []
    for claim in claims:
        if not claim.is_factual:
            verified.append(VerifiedClaim(claim, "skipped", 0.0, "n/a"))
        elif not claim.citation_ids:
            verified.append(VerifiedClaim(claim, "unsupported", 0.0, "n/a"))

    factual_cited = [c for c in claims if c.is_factual and c.citation_ids]
    for batch in batch_claims(factual_cited, contexts):
        questions: dict[str, Question] = {
            claim.claim_id: _claim_question(claim, contexts) for claim in batch
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
        metadata={"job": "revision"},
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
