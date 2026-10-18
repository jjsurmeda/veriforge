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

#: How many post-sanitize passages the evidence checks read, and the character
#: budget their batched questions share. Both are about the checks that remain
#: — the entity guard and the conflict pairs — not about a sufficiency question,
#: which ADR-006 as corrected no longer asks (the gate is the rerank rubric).
TOP_CHUNKS_FOR_CHECKS = 5
EVIDENCE_CHARS = 9_000

# --- the evidence gate (ADR-006 as corrected) --------------------------------

#: How many of the best-graded passages the gate averages.
GATE_TOP_N = 3


def rubric_mean_top3(grades: list[float]) -> float | None:
    """The gate's own number: the mean grade of the best `GATE_TOP_N` passages.

    `None` when there is nothing to average — no passage was graded, or the
    rerank scored none of them. **`None` is not 0.0**, and the difference is the
    whole safety direction: 0.0 means "the rubric graded every passage
    off-topic", which is a measurement and a failing gate; `None` means "there
    was no reading", which the caller degrades on its own terms (see
    `evidence_stage._read_answers`).

    Averaging three rather than taking the best is what separates a gist
    question from a lucky passage. One strong passage in a fan-out is the
    normal state of retrieval — the third-best chunk in a fan-out almost never
    answers anything, and a max would grade every corpus on it.
    """
    usable = [g for g in grades if g is not None]
    if not usable:
        return None
    ordered = sorted(usable, reverse=True)
    return sum(ordered[:GATE_TOP_N]) / len(ordered[:GATE_TOP_N])


def rubric_gate_passes(mean_top3: float | None, floor: float) -> bool:
    """One comparison. A missing reading fails, which is the safe direction:
    an unreachable grader is not evidence that the corpus can answer."""
    return mean_top3 is not None and mean_top3 >= floor


def rubric_grades(winners: list[ScoredChunk]) -> list[float]:
    """The rubric's grade for each post-sanitize winner.

    `rerank_score` IS the answer-containment expected level, normalised to 0-1
    by `retrieval/rerank.answer_containment_score` — the rubric ranks by
    expected level rather than by argmax precisely so this number carries the
    distribution the grader returned.
    """
    return [c.rerank_score for c in winners if c.rerank_score is not None]

# When the evidence is clearly absent, the corrective re-query is another
# 13-15 s to reach the same abstention, so it is skipped. Both bounds sit far
# below their floors because the failure direction of a skip is a decline that
# could have been an answer.
#
# The gate bound is re-derived from the rubric gate's own calibration
# (R2a-2 item 2), not inherited from the `sufficient` reading it replaced.
# `scripts/calibrate_gate.py` recorded a mean-of-top-3 for all 53 gated items of
# the books set and all 12 of the entity-mismatch set; the lowest value in that
# table for an item the correction could conceivably rescue is 0.224
# (`outside-whitman`, an answerable item), and the should-decline values the
# shipped 0.455 floor still blocks sit between outside-dracula's 0.007 and
# ml-de-bovary-animal's 0.441. 0.10 therefore misses some blocked rows either
# way and is not a floor replica: it is a "clearly absent" bound, and sitting
# below every answerable reading that could be rescued and above the 0.0 a run
# with nothing usable produces is what makes a skip fire only when a re-query
# has nothing to find. Higher failing readings (0.520-0.559, e.g.
# `outside-holmes-boston`) are no longer on any wrong side: above the floor
# they generate, and IsUse is the check that decides them.
#
# It replaces `RETRY_SKIP_SUFFICIENT_MAX = 0.005`, which R2a had moved down from
# 0.02 and which was by then nearly inert — under the `sufficient` reading almost
# nothing scored that low, so the skip bought almost nothing while still
# carrying a decision. The bound is re-derivable rather than inherited precisely
# because the signal it was derived from is no longer the gate.
#
# The entity bound keeps its value and its job: a matched entity still blocks
# the skip outright, which is the reading that directly contradicts "clearly
# absent". Both bounds are admin-overridable (`retrieval.retry_skip_*`); a null
# disables that half of the test.
RETRY_SKIP_RUBRIC_MAX = 0.10
RETRY_SKIP_ENTITY_MAX = 0.50

# The conflict check asks one question per candidate PAIR of passages, batched
# into a single DecisionEngine call. With at most
# TOP_CHUNKS_FOR_CHECKS sides there are 10 pairs, which is the cap: it
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
    THIS entity?", batched into the post-sanitize evidence call — the same call
    that carries the conflict pairs, so there is no extra round trip. Skipped
    when the question names no entity or nothing survived to the top-k.

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
    gate_mean_top3: float | None,
    entity_max: float | None,
    entity_measured: bool,
    entity_ok: bool,
) -> bool:
    """Is the evidence CLEARLY absent, so the corrective re-query is pointless?

    Two readings, and both must be far below their floor:

    * **The gate** — and "far below" is now a genuinely small band rather than
      the near-inert 0.005 it was under the `sufficient` reading. The gate is
      the mean grade of the best three passages, so it is 0.0 only when nothing
      was graded or nothing was retrieved; the lowest band the calibration ever
      *measured* is 0.224 (`outside-whitman`, an answerable item whose evidence
      the correction is the last chance for). 0.10 sits below every reading the
      calibration recorded and above the readings a run with no usable evidence
      produces, so the skip fires exactly where a re-query cannot help and
      nowhere else.

      The old bound was derived from KI-70's `sufficient` replay (lowest rescued
      reading 0.01, of 7 rescues in 238 runs) and R2a moved it to 0.005, which
      made it nearly inert — almost nothing scored that low. It is re-derived
      here from the gate's own distribution rather than inherited.
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
    gate_bound = runtime_value("retrieval.retry_skip_rubric_max", RETRY_SKIP_RUBRIC_MAX)
    # An admin can turn the skip off by setting the bound to null.
    if gate_bound is None:
        return False
    # No reading at all is clearly absent: nothing was retrieved, or nothing was
    # graded, and a re-query of the same corpus cannot change either.
    if gate_mean_top3 is None:
        return True
    return gate_mean_top3 <= float(gate_bound)


def _conflict_sides(winners: list[ScoredChunk]) -> list[ScoredChunk]:
    """The top passages eligible to be a conflict side: at most
    `TOP_CHUNKS_FOR_CHECKS`, one per document.

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
        if len(sides) >= TOP_CHUNKS_FOR_CHECKS:
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
    budget = EVIDENCE_CHARS // max(1, len(sides) * (len(sides) - 1) // 2)
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
