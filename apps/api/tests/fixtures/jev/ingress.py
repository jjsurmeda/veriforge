"""Hand-written Jev response fixture for tests. testing.md forbids live
calls; this shape mirrors OpenRouter System One's real response contract
(verified 2026-09-23 against the live endpoint — see decisions/jev.py)."""

INGRESS_RESPONSE = {
    "answers": {
        "guard_injection": {"noul": 0.04},
        "guard_jailbreak": {"noul": 0.02},
        "guard_pii": {"noul": 0.10},
        "off_topic": {"noul": 0.05},
        "intent": {
            "choice": "lookup",
            "probabilities": {
                "chitchat": 0.02,
                "lookup": 0.78,
                "compare": 0.05,
                "summarize": 0.05,
                "multi-part": 0.05,
                "follow-up": 0.05,
            },
        },
        "source": {
            "choice": "both",
            "probabilities": {"upload": 0.20, "web": 0.10, "both": 0.70},
        },
        "complexity": {
            "choice": "single",
            "probabilities": {"single": 0.90, "multi": 0.10},
        },
        "risk": {"choice": "low", "probabilities": {"low": 0.95, "high": 0.05}},
        "lexical_weight": {"score": 0.35},
    }
}
