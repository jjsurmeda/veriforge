"""Hand-written Jev response fixture for tests. testing.md forbids live
calls; this shape mirrors decisions/jev.py's module docstring contract."""

INGRESS_RESPONSE = {
    "answers": {
        "guard_injection": {
            "probability": 0.04,
            "reasoning": "no instruction override attempts detected",
        },
        "guard_jailbreak": {"probability": 0.02},
        "guard_pii": {"probability": 0.10},
        "off_topic": {"probability": 0.05},
        "intent": {
            "value": "lookup",
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
            "value": "both",
            "probabilities": {"upload": 0.20, "web": 0.10, "both": 0.70},
        },
        "complexity": {
            "value": "single",
            "probabilities": {"single": 0.90, "multi": 0.10},
        },
        "risk": {"value": "low", "probabilities": {"low": 0.95, "high": 0.05}},
        "lexical_weight": {"value": 0.35, "reasoning": "natural-language question"},
    }
}
