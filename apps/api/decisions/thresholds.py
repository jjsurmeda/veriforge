"""Decision thresholds per engine (TRD §8).

A Jev 0.7 is not the same as a fallback 0.7 — the two engines are
calibrated differently, so every threshold is keyed by engine. The
defaults here come from TRD §8's catalogue; `settings.data.thresholds`
(JSON) can override any cell without a redeploy.
"""

from typing import Literal

from runtime import get_runtime_settings

Engine = Literal["jev", "fallback"]

# decision name -> engine -> threshold. Missing cells mean "use the other
# engine's value" — Jev is the reference scale, with admin overrides per engine.
_DEFAULTS: dict[str, dict[Engine, float]] = {
    "guard_injection_block": {"jev": 0.85, "fallback": 0.85},
    "guard_injection_warn": {"jev": 0.60, "fallback": 0.60},
    "guard_jailbreak_block": {"jev": 0.85, "fallback": 0.85},
    "guard_jailbreak_warn": {"jev": 0.60, "fallback": 0.60},
    "guard_pii_warn": {"jev": 0.70, "fallback": 0.70},
    "off_topic_warn": {"jev": 0.80, "fallback": 0.80},
    "choice_min_confidence": {"jev": 0.50, "fallback": 0.50},
    # KI-37: `library` is the one intent that skips retrieval and answers from
    # the document list, so a merely probable `library` is the expensive kind
    # of wrong. "What does the AW-2000 package contain?" scored 0.6-0.95 as
    # `library` across three fast20 runs and was answered with the corpus's
    # internal filenames (faithfulness 0.000, no citations). 0.70 is the
    # generic pick floor (0.50) plus a deliberate margin: below it, the
    # question takes the retrieval path and the document is read, not listed.
    "library_min_confidence": {"jev": 0.70, "fallback": 0.70},
    "chunk_injection_drop": {"jev": 0.70, "fallback": 0.70},
    # Answer-first (batch A, 2026-09-28): generate at or above the floor,
    # one rewrite + retry below it, then abstain.
    #
    # ADR-006 as corrected (2026-10-15): the evidence gate is the reranker's
    # **answer-containment rubric** — the mean grade of the best three
    # post-sanitize passages. There is no second gate: `sufficient`, its
    # threshold and its admin key are gone. The number below is calibrated, not
    # chosen; the full table is in the R2a-2 report
    # (`scripts/calibrate_gate.py` is what produced it).
    #
    #     cutoff   confident wrong   false abstention
    #        0.40            5                1
    #        0.48            2                1
    #        0.55            0                2      <- shipped
    #        0.645           0                8
    #
    # **No cutoff reaches 0 confident wrong and ≤ 1 false abstention.** 0.645
    # does reach 0, and costs eight answerable items — a quarter of the corpus
    # — which is not a threshold, it is abstaining from the product. 0.55 is
    # the cheapest zero, and the two items it costs are named in the report.
    #
    # The margin on the books set is real but narrow, and stated as it is: the
    # verdict is identical anywhere in (0.520, 0.554]. Below is
    # `outside-holmes-boston` at 0.520, the highest should-decline; above is
    # `broad-bovary` at 0.554, the lowest answerable. 0.55 sits 0.030 above the
    # first and 0.004 below the second, and **0.004 is thin** — one gist item
    # inside that window would flip. A re-run of the calibration that moves
    # `broad-bovary` down by 0.005 has to reopen this number.
    #
    # The two should-decline items that clear 0.55 are both from the
    # entity-mismatch set (`cf-k9-charge` 0.634, `em-aw-package` 0.544), and
    # **the entity guard is what holds them**: their max entity readings are
    # 0.450 and 0.090, both under the `entity_match` floor of 0.50. That is
    # exactly the division of labour ADR-006 describes, measured rather than
    # assumed — and it is why the floor is shipped at 0.55 and not at 0.645.
    "rubric_mean_top3": {"jev": 0.55, "fallback": 0.55},
    "conflict_disclose": {"jev": 0.60, "fallback": 0.60},
    "output_toxicity_block": {"jev": 0.85, "fallback": 0.85},
    # Slice 6: 0.60 abstained Deep runs on corpus-answerable questions —
    # live smoke showed Jev "sufficient" at p=0.57 killed by the gate.
    # Aligned with choice_min_confidence (the generic pick floor).
    "controller_sufficient": {"jev": 0.50, "fallback": 0.50},
    # P2a item 3: a reply that says the sources cannot answer (the
    # `says_not_in_sources` shape) is recorded as an abstention
    # post-delivery. 0.70 is the generic 0.50 pick floor plus a deliberate
    # margin: a false flip strips the citations from a real answer, while
    # partial answers that state what is missing (TR-4) answer "no" and
    # never reach the bar.
    "prose_decline": {"jev": 0.70, "fallback": 0.70},
    # P2a item 4: a per-passage Noul asks "is this passage about the
    # entity the question names?", batched into the post-sanitize
    # sufficiency call. 0.50 is the generic pick floor: a passage matches
    # the entity when the judge is at least as likely to say yes as no, and
    # the run abstains only when NO top-k passage matches. The question
    # names no entity -> the check is skipped, never an abstention.
    "entity_match": {"jev": 0.50, "fallback": 0.50},
}


DISPLAY_THRESHOLDS: dict[str, str] = {
    "guard_injection": "guard_injection_block",
    "guard_jailbreak": "guard_jailbreak_block",
    "guard_pii": "guard_pii_warn",
    "off_topic": "off_topic_warn",
    # The evidence gate is the rubric's mean-of-top-3 (ADR-006 as corrected), so
    # this is the number the `evidence` decision row is shown against.
    "evidence": "rubric_mean_top3",
    "rubric": "rubric_mean_top3",
    "conflict": "conflict_disclose",
    "controller": "controller_sufficient",
    "output_toxicity": "output_toxicity_block",
    "output_secrets": "guard_pii_warn",
    "prose_decline": "prose_decline",
    "entity": "entity_match",
}


def threshold(
    name: str, engine: Engine, overrides: dict[str, dict[str, float]] | None = None
) -> float:
    """Look up a threshold. `overrides` is settings.data['thresholds']."""
    runtime = get_runtime_settings()
    if overrides is None and runtime is not None:
        value = runtime.get("thresholds", {})
        if isinstance(value, dict):
            overrides = value
    if overrides and name in overrides and engine in overrides[name]:
        return overrides[name][engine]
    try:
        return _DEFAULTS[name][engine]
    except KeyError as exc:
        raise KeyError(f"unknown decision threshold: {name!r} for engine {engine!r}") from exc


def display_threshold(name: str, engine: Engine) -> float | None:
    threshold_name = DISPLAY_THRESHOLDS.get(name)
    if threshold_name is None and name.startswith("chunk_injection_"):
        threshold_name = "chunk_injection_drop"
    # P2a item 4: one Noul per (passage, entity) pair, named entity_<passage>_<entity>
    # (the second index is KI-72's). The prefix test covers both.
    if threshold_name is None and name.startswith("entity_"):
        threshold_name = "entity_match"
    # KI-34, lane E item 1: the conflict check asks one question per candidate
    # PAIR of passages, named conflict_<i>. `DISPLAY_THRESHOLDS` only carries
    # the bare `conflict`, so every real conflict decision resolved to None and
    # reached the trace with a value and no threshold — the one gate row in the
    # evidence-gate card that could not say what it was compared against.
    # Fixed here rather than at the caller: `display_threshold` is the single
    # place `graph/runner.py`'s emitter turns a decision name into the number
    # shown beside it, in Auto and Deep alike, so this closes the gap for every
    # gate instead of for one call site.
    if threshold_name is None and name.startswith("conflict_"):
        threshold_name = "conflict_disclose"
    if threshold_name is None:
        return None
    try:
        return threshold(threshold_name, engine)
    except KeyError:
        return None
