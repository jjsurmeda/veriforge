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
    # one rewrite + retry below it, then abstain. 0.05 measured on the
    # books acceptance set: answer-class items scored 0.06-0.49 while
    # not-in-sources items scored 0.01-0.04, so 0.05 separates the groups
    # (thin margin — rerank score is the fallback second signal if it
    # closes). sufficient_retry is removed: with one retry there is one bar.
    "sufficient_abstain": {"jev": 0.05, "fallback": 0.05},
    # The second signal closed (KI-26, D2 item 4). `sufficient` alone can't
    # separate answer from should-abstain (margin -0.06 in both D1
    # acceptance runs), but the max Jev rerank score of the post-sanitize
    # winners can. Offline replay of D1's two runs (max rerank score in the
    # final retrieval event, per class):
    #
    # | run      | answer items (n=23) min | should-abstain (n=14) max |
    # | 183311   | 0.70 (broad-frankenstein) | 0.49 (ml-fr-outside)    |
    # | 184634   | 0.73 (broad-frankenstein) | 0.52 (ml-fr-outside)    |
    #
    # 0.60 clears both sides in both runs (0.10-0.13 above the answer min,
    # 0.08-0.11 below the abstain max); 0.50 loses ml-fr-outside in 184634
    # (0.52 answers). Offline replay: 40/41 at 0.50-0.65 in run 183311 and
    # 0.55-0.65 in 184634, only xl-en-wukong-master (KI-27, content) left.
    # The fallback cell is UNMEASURED — only Jev-answered scores were seen;
    # it mirrors jev because Jev is the reference scale. Applies only to
    # scores JevRerank answered (NVIDIA/Cohere use other scales; fused
    # order is 1/(1+i), top always 1.0).
    "rerank_abstain": {"jev": 0.60, "fallback": 0.60},
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
}


DISPLAY_THRESHOLDS: dict[str, str] = {
    "guard_injection": "guard_injection_block",
    "guard_jailbreak": "guard_jailbreak_block",
    "guard_pii": "guard_pii_warn",
    "off_topic": "off_topic_warn",
    "sufficient": "sufficient_abstain",
    "relevance": "rerank_abstain",
    "conflict": "conflict_disclose",
    "controller": "controller_sufficient",
    "output_toxicity": "output_toxicity_block",
    "output_secrets": "guard_pii_warn",
    "prose_decline": "prose_decline",
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
    if threshold_name is None:
        return None
    try:
        return threshold(threshold_name, engine)
    except KeyError:
        return None
