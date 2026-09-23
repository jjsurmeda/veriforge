"""Decision thresholds per engine (TRD §8).

A Jev 0.7 is not the same as a fallback 0.7 — the two engines are
calibrated differently, so every threshold is keyed by engine. The
defaults here come from TRD §8's catalogue; `settings.data.thresholds`
(JSON) can override any cell without a redeploy.
"""

from typing import Literal

Engine = Literal["jev", "fallback"]

# decision name -> engine -> threshold. Missing cells mean "use the other
# engine's value" — Jev is the reference scale, fallback inherits until
# slice 7's admin UI tunes it against shadow-mode data.
_DEFAULTS: dict[str, dict[Engine, float]] = {
    "guard_injection_block": {"jev": 0.85, "fallback": 0.85},
    "guard_injection_warn": {"jev": 0.60, "fallback": 0.60},
    "guard_jailbreak_block": {"jev": 0.85, "fallback": 0.85},
    "guard_jailbreak_warn": {"jev": 0.60, "fallback": 0.60},
    "guard_pii_warn": {"jev": 0.70, "fallback": 0.70},
    "off_topic_warn": {"jev": 0.80, "fallback": 0.80},
    "choice_min_confidence": {"jev": 0.50, "fallback": 0.50},
    "chunk_injection_drop": {"jev": 0.70, "fallback": 0.70},
    "sufficient_retry": {"jev": 0.60, "fallback": 0.60},
    "sufficient_abstain": {"jev": 0.35, "fallback": 0.35},
    "conflict_disclose": {"jev": 0.60, "fallback": 0.60},
    "output_toxicity_block": {"jev": 0.85, "fallback": 0.85},
    # Slice 6: 0.60 abstained Deep runs on corpus-answerable questions —
    # live smoke showed Jev "sufficient" at p=0.57 killed by the gate.
    # Aligned with choice_min_confidence (the generic pick floor).
    "controller_sufficient": {"jev": 0.50, "fallback": 0.50},
}


def threshold(
    name: str, engine: Engine, overrides: dict[str, dict[str, float]] | None = None
) -> float:
    """Look up a threshold. `overrides` is settings.data['thresholds']."""
    if overrides and name in overrides and engine in overrides[name]:
        return overrides[name][engine]
    try:
        return _DEFAULTS[name][engine]
    except KeyError as exc:
        raise KeyError(f"unknown decision threshold: {name!r} for engine {engine!r}") from exc
