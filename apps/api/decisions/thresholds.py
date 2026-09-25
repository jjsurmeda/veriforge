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


DISPLAY_THRESHOLDS: dict[str, str] = {
    "guard_injection": "guard_injection_block",
    "guard_jailbreak": "guard_jailbreak_block",
    "guard_pii": "guard_pii_warn",
    "off_topic": "off_topic_warn",
    "sufficient": "sufficient_retry",
    "conflict": "conflict_disclose",
    "controller": "controller_sufficient",
    "output_toxicity": "output_toxicity_block",
    "output_secrets": "guard_pii_warn",
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
