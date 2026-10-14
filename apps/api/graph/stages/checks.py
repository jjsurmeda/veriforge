"""The questions the evidence stage asks, and how it reads the answers.

Pure functions: each builds a `Noul`/`Choice`/`Score` for the DecisionEngine,
or turns one batch of answers into a verdict. The stage that runs them lives
in `evidence_stage.py`; nothing here touches the database or the run.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from itertools import combinations

from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk
from runtime import runtime_value
from schemas.decisions import Answer, Choice, Noul, Score

TOP_CHUNKS_FOR_SUFFICIENT = 5
SUFFICIENT_EVIDENCE_CHARS = 9_000

# When the evidence is clearly absent, the corrective re-query is another
# 13-15 s to reach the same abstention, so it is skipped. Both bounds sit far
# below their floors because the failure direction of a skip is a decline that
# could have been an answer.
#
# The sufficiency bound is 0.005 and that number comes from the replay table
# in KI-70, not from taste: of 238 recorded Auto runs that took the corrective
# retrieval, 231 still abstained, and **among the 7 the correction rescued,
# sufficiency went as low as 0.01**. So 0.01 is the lowest reading the
# correction has been known to rescue, and the skip must not fire at or above
# it. It was 0.02 until the relevance reading came out of this test (ADR-006,
# R2a item 4): the old test demanded a corroborating relevance score as well as
# a low sufficiency, and that second reading is what kept the bound from being
# the last word. With it gone, the bound has to carry the whole decision on its
# own and has to sit below the lowest recorded rescue.
#
# The consequence is that the skip is now nearly inert, which is the honest
# price of not having a second signal: almost nothing scores below 0.005.
# Removing the skip altogether is the ADR-006-pure option and costs one extra
# 13-15 s pass on every decline; that is a latency decision for phase 3, not
# one to make silently here.
#
# The entity bound keeps its value and its job: a matched entity still blocks
# the skip outright, which is the reading that directly contradicts "clearly
# absent". Both bounds are admin-overridable (`retrieval.retry_skip_*`); a null
# disables that half of the test.
RETRY_SKIP_SUFFICIENT_MAX = 0.005
RETRY_SKIP_ENTITY_MAX = 0.50

# The conflict check asks one question per candidate PAIR of passages, batched
# into a single DecisionEngine call. With at most
# TOP_CHUNKS_FOR_SUFFICIENT sides there are 10 pairs, which is the cap: it
# bounds one call's prompt size without dropping a pair that could be the real
# conflict.
CONFLICT_MAX_PAIRS = 10

# Model codes (AW-2000, R-7, K9) and capitalised names ("Kestrel", "Ridgeline",
# "Montbriv"), conservatively: a wrong extraction costs one extra "no" the
# other passages can still offset, and an empty list skips the check — which
# never abstains.
_MODEL_CODE_RE = re.compile(r"\b[A-Z]{1,4}-?\d{1,4}(?:[-/]\d{1,4})*\b")
_CAPITALISED_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|the))*(?=\b)")
_ENTITY_STOP = {
    "Compare",
    "How",
    "What",
    "Why",
    "When",
    "Where",
    "Who",
    "Which",
    "Does",
    "Did",
    "Can",
    "Could",
    "Should",
    "Shall",
    "May",
    "Might",
    "The",
    "A",
    "An",
    "This",
    "That",
    "These",
    "Those",
    "There",
    "Here",
    "It",
    "I",
    "You",
    "We",
    "They",
    "He",
    "She",
    "My",
    "Your",
    "Our",
    "Their",
    "In",
    "On",
    "At",
    "For",
    "With",
    "From",
    "About",
    "Into",
    "Over",
    "Under",
    "Per",
    "Also",
    "Please",
    "Note",
    "Hi",
    "Hello",
    "Thanks",
    "Thank",
    "Yes",
    "No",
    # Openers the ASCII-range regex still matches in FR/DE/ES.
    "Quel",
    "Quels",
    "Qui",
    "Quand",
    "Comment",
    "Pourquoi",
    "Wer",
    "Was",
    "Wie",
    "Wann",
    "Wo",
    "Warum",
    "Welche",
    "Welcher",
    "Welches",
}


def _sufficient_question(question: str, top_contexts: list[ExpandedContext]) -> Noul:
    """Is the evidence enough to answer correctly and completely?

    Whole children first, in rank order; parent context follows only if the
    budget has room after every child that fits took its turn. Interleaving
    each entry's parent before the next entry's child instead let the first
    source's parent eat the budget, so a two-source judge saw one of them.
    """
    remaining = SUFFICIENT_EVIDENCE_CHARS
    entries: list[str] = []
    for i, context in enumerate(top_contexts):
        if remaining <= 0:
            break
        text = context.chunk.text[:remaining]
        remaining -= len(text)
        entries.append(f"[{i + 1}] [matched passage]\n{text}")
    parents: list[str] = []
    for i, context in enumerate(top_contexts):
        if remaining <= 0 or i >= len(entries):
            break
        parent = context.context_text
        if parent == context.chunk.text:
            continue
        excerpt = parent[:remaining]
        parents.append(f"[{i + 1}] [parent context]\n{excerpt}")
        remaining -= len(excerpt)
    evidence = "\n\n".join([*entries, *parents]) or "(no evidence retrieved)"
    return Noul(
        prompt=(
            "Do the following retrieved chunks together contain enough "
            "evidence to answer the question correctly and completely? "
            "Answer yes only if the answer is fully grounded in the "
            f"evidence.\n\n[question]\n{question}\n\n[evidence]\n{evidence}"
        )
    )


def named_entities(question: str) -> list[str]:
    """The entities a question names, conservatively.

    Empty means "no named entity — skip the check". A name at the very start
    of the question is excluded: it may be a sentence opener, and the safe
    direction is to skip (skipping never abstains), not to guess. The
    capitalised-name regex still misses ALL-CAPS titles and quoted names, and
    keeps a mid-question sentence opener ("Note: ...").
    """
    entities: list[str] = []
    for match in _MODEL_CODE_RE.finditer(question):
        entities.append(match.group(0))
    for match in _CAPITALISED_NAME_RE.finditer(question):
        entity = match.group(0)
        if entity.split(" ")[0] in _ENTITY_STOP:
            continue
        if match.start() == 0:
            continue
        entities.append(entity)
    return list(dict.fromkeys(entities))


def _entity_passage_questions(
    question: str, entities: list[str], top_contexts: list[ExpandedContext]
) -> dict[str, Noul]:
    """One Noul per (top-k passage, named entity) pair, "is this passage about
    THIS entity?", batched into the existing post-sanitize sufficiency call — no
    extra round trip. Skipped when the question names no entity or nothing
    survived to the top-k.

    One entity per question, never the conjunction: a conjunction over passages
    can never be satisfied when the rerank stage deliberately splits a compare
    item's top-k by entity, because each passage is about exactly one of them.
    Asking per (passage, entity) makes each reading mean what it says, and lets
    the caller ask the question the product needs: "is there at least one
    passage about this entity?", per entity.
    """
    if not entities or not top_contexts:
        return {}
    questions: dict[str, Noul] = {}
    for passage_index, context in enumerate(top_contexts):
        passage = context.chunk.text[:1500]
        for entity_index, entity in enumerate(entities):
            questions[f"entity_{passage_index}_{entity_index}"] = Noul(
                prompt=(
                    f"The question below names the entity '{entity}'. "
                    "Does this passage concern that same entity — the "
                    "same product or model family, the same organisation, or the "
                    "same named place or person? Answer yes only if the passage is "
                    "about the named entity; a passage about a different product, "
                    "even in the same category, is not about it.\n\n"
                    f"[question]\n{question}\n\n"
                    f"[passage]\n{passage}"
                )
            )
    return questions


def _entity_passage_decision(
    answers: dict[str, Answer],
    names: Iterable[str],
    entity_count: int,
    threshold_value: float,
) -> tuple[bool, float | None]:
    """Does the evidence cover EVERY entity the question names?

    A passage may be about any one of the named entities, but the run may only
    answer if each one of them is actually covered — otherwise a compare
    question with evidence for only one side answers half of it. So this is
    "every entity has at least one passing passage", not "some passage passed".

    Returns the verdict and the maximum reading across the whole batch, the
    latter being what `_evidence_clearly_absent` judges the retry against. With
    one entity this is exactly the old "any passage matched" rule.
    """
    values = [float(answers[name].value) for name in names]
    if not values:
        return True, None
    # Values arrive passage-major: passage 0's readings for every entity, then
    # passage 1's, and so on.
    covered = [
        any(
            values[passage * entity_count + entity] >= threshold_value
            for passage in range(len(values) // entity_count)
        )
        for entity in range(entity_count)
    ]
    return all(covered), max(values)


def _evidence_clearly_absent(
    *,
    p_sufficient: float,
    entity_max: float | None,
    entity_measured: bool,
    entity_ok: bool,
) -> bool:
    """Is the evidence CLEARLY absent, so the corrective re-query is pointless?

    Two readings, and both must be far below their floor:

    * Sufficiency is the evidence check itself (ADR-006), and its bound sits
      below the lowest reading the correction has ever been known to rescue.
    * A matched entity blocks the skip: it is the one signal that contradicts
      "clearly absent" directly, and it is the guard that catches a question
      whose evidence is all about the wrong thing.

    The third reading this used to need — a relevance score — is gone with the
    relevance floor (ADR-006, R2a item 4). It was a lexical-overlap number
    standing in for "is this evidence relevant", which for a gist question it
    demonstrably cannot be: the recorded `broad-alice` run scored the correct
    passages 0.36 on relevance and 0.97 on the entity check.
    """
    if entity_measured and entity_ok:
        return False
    entity_bound = runtime_value("retrieval.retry_skip_entity_max", RETRY_SKIP_ENTITY_MAX)
    if entity_max is not None and entity_bound is not None and entity_max > float(entity_bound):
        return False
    sufficient_bound = runtime_value(
        "retrieval.retry_skip_sufficient_max", RETRY_SKIP_SUFFICIENT_MAX
    )
    # An admin can turn the skip off by setting the bound to null.
    if sufficient_bound is None:
        return False
    return p_sufficient <= float(sufficient_bound)


def _conflict_sides(winners: list[ScoredChunk]) -> list[ScoredChunk]:
    """The top passages eligible to be a conflict side: at most
    `TOP_CHUNKS_FOR_SUFFICIENT`, one per document.

    One per document because a conflict is a disagreement *between sources*.
    Two chunks of the same document are the same source, and pairing them
    would let the checker report a document disagreeing with itself.
    """
    sides: list[ScoredChunk] = []
    seen: set[object] = set()
    for chunk in winners:
        key = chunk.document_id or chunk.chunk_id
        if key in seen:
            continue
        seen.add(key)
        sides.append(chunk)
        if len(sides) >= TOP_CHUNKS_FOR_SUFFICIENT:
            break
    return sides


def _conflict_pair_questions(
    sides: list[ScoredChunk], question: str
) -> dict[str, Noul | Choice | Score]:
    """One DecisionEngine question per candidate pair of sides, batched into a
    single `decide` call (TRD §8 supports several questions per call).

    A question per PAIR is what makes the answer attributable: the pair that
    fires names the two passages, and those two are the sides the event shows.
    A single "do ANY two of these disagree?" question cannot: the code would
    have had to split the document ids at the midpoint, so the UI could show a
    conflict whose two sides agreed with each other (TR-5 promises "cites both
    sides").

    At most `CONFLICT_MAX_PAIRS` pairs, so a long passage list cannot turn one
    call into an unbounded question set.
    """
    budget = SUFFICIENT_EVIDENCE_CHARS // max(1, len(sides) * (len(sides) - 1) // 2)
    questions: dict[str, Noul | Choice | Score] = {}
    for index, (left, right) in enumerate(combinations(sides, 2)):
        if index >= CONFLICT_MAX_PAIRS:
            break
        questions[f"conflict_{index}"] = Noul(
            prompt=(
                "Do these two passages assert INCOMPATIBLE values for the "
                "same fact — two different values, where a reader could not "
                "hold both? Say yes only for a direct factual contradiction "
                "on a fact the question depends on. Say no if they agree, if "
                "they are about different facts, or if one is merely more "
                "detailed than the other.\n\n"
                f"[question]\n{question}\n\n"
                f"[passage A — {left.document_name or left.source_type}]\n"
                f"{left.text[:budget]}\n\n"
                f"[passage B — {right.document_name or right.source_type}]\n"
                f"{right.text[:budget]}"
            )
        )
    return questions
