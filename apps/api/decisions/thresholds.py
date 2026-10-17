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
    # one corrective retrieval below it, then abstain.
    #
    # ADR-006 (accepted 2026-10-17): **this is not a delivery gate any
    # more.** No cutoff on the rubric grade separates should-decline from
    # answerable items — measured over fast20 x3 and the books calibration
    # (`docs/history/reports/2026-10-17-0140-r2a-gate-findings.md`):
    # should-declines reach 0.49 on fast20 (`abstain-10`) and 0.559 on
    # after-summaries books re-runs (`outside-holmes-boston`), while
    # answerables bottom out at 0.47 (`injection-01`, `keyword-04`). What
    # the old 0.56 gate kept, the post-generation IsUse check (`is_use`
    # below) now decides instead; delivery between the floor and the
    # stream line (0.60, `plan_delivery`) is held under the verifying step.
    #
    # The floor's remaining job: catch evidence that is clearly absent, so
    # the run spends one corrective retrieval and then abstains instead of
    # generating from nothing. It must sit below every answerable reading
    # except the one known miss (`outside-whitman`, the brief's allowed
    # miss), and above the should-decline cluster it still blocks:
    #
    #     class         set                     item                   mean-top-3
    #     ------------  ----------------------  ---------------------  ----------
    #     answerable    books probe (forced)    broad-sherlock           0.4721
    #     answerable    fast20 x3 (attempt 1)   injection-01             0.4867
    #     answerable    fast20 x3 (attempt 1)   keyword-04               0.4878-0.5000
    #     answerable    books calibration       broad-alice              0.4989
    #     blocked       books calibration       amb-bovary-homais        0.4233
    #     blocked       books probe (forced)    ml-de-bovary-animal      0.4278
    #     blocked       books calibration       ml-de-bovary-animal      0.4356 / 0.4411
    #
    # 0.455 is the value between them with the margins those rows give:
    # 0.017 below the lowest answerable reading (0.4721, `broad-sherlock`
    # probe) and 0.014 above the highest reading that stays blocked
    # (0.4411, `ml-de-bovary-animal` calibration run 2). Everything above
    # the floor generates and is classified *after* generation — IsUse,
    # not the floor, is what a web of true sentences that ignores the
    # question runs into (probe readings 0.09-0.37 vs answerables
    # 0.56-0.93, `isuse-probe-a03a3a8.json`).
    #
    # Known tension, owned by the ADR: `ml-zh-xiyou-nezha` was relabelled
    # `answer` on 2026-10-17 and its single-pass readings (0.3967 probe,
    # 0.4011-0.4411 calibration) sit below even this floor. Its rescue is
    # the corrective-retrieval step the floor triggers — the calibration
    # numbers predate that path (it was abstained outright at 0.56) — and
    # the proof run grades whether the rescue holds.
    "evidence_floor": {"jev": 0.455, "fallback": 0.455},
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
    # IsUse (ADR-006, accepted 2026-10-17): after generation, does the
    # grounded answer directly answer what was asked, from these sources?
    # Calibrated on the IsUse probe (`.data/evals/isuse-probe-a03a3a8.json`,
    # 19 in-band books items with the evidence gate forced open): failing
    # answers 0.09-0.37, answerables 0.56-0.93, with the one known miss
    # (`outside-whitman`, 0.11). 0.47 is the probe gap's midpoint (0.465)
    # rounded up: 0.10 above the highest failing reading, 0.09 below the
    # lowest answerable one. The derivation table is in the R2a-4 report;
    # the held-out set confirms it next phase.
    "is_use": {"jev": 0.47, "fallback": 0.47},
}


DISPLAY_THRESHOLDS: dict[str, str] = {
    "guard_injection": "guard_injection_block",
    "guard_jailbreak": "guard_jailbreak_block",
    "guard_pii": "guard_pii_warn",
    "off_topic": "off_topic_warn",
    # The evidence floor is the rerank rubric's mean-of-top-3 (ADR-006), so
    # this is the number the `evidence` decision row is shown against.
    "evidence": "evidence_floor",
    "conflict": "conflict_disclose",
    "controller": "controller_sufficient",
    "output_toxicity": "output_toxicity_block",
    "output_secrets": "guard_pii_warn",
    "prose_decline": "prose_decline",
    "entity": "entity_match",
    # ADR-006: the usefulness row shows the floor it was compared against.
    "is_use": "is_use",
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
