"""Output guardrail tests (slice 6, TRD §10/§11): pure redaction + fake
engine for the toxicity/leak decisions — no live calls (testing.md)."""

import pytest

from decisions.output_guard import guard_output, redact_secrets
from schemas.decisions import Answer


class _FakeEngine:
    def __init__(self, answers: dict[str, Answer]) -> None:
        self._answers = answers
        self.calls: list[list[str]] = []

    async def decide(self, *, state, questions):  # type: ignore[no-untyped-def]
        self.calls.append(list(questions))
        return {
            name: self._answers.get(
                name, Answer(engine="jev", latency_ms=1, value=0.0, probability=0.0)
            )
            for name in questions
        }


def _answer(value: float) -> Answer:
    return Answer(engine="jev", latency_ms=1, value=value, probability=value)


class TestRedactSecrets:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("reach me at jane.doe@corp.example.com today", "EMAIL"),
            ("use key sk-abcdefghijklmnopqrstuvwx for it", "API_KEY"),
            ("token ghp_abcdefghijklmnopqrstuvwxyz0123456789 leaks", "API_KEY"),
            ("AKIAIOSFODNN7EXAMPLE in config", "API_KEY"),
            ("-----BEGIN RSA PRIVATE KEY-----", "PRIVATE_KEY"),
            ("card 4111 1111 1111 1111 ends fine", "CREDIT_CARD"),
            ('password = "aaaaaaaaaaaaaaaa" in the file', "SECRET"),
        ],
    )
    def test_substitutes_with_tagged_marker(self, text: str, kind: str) -> None:
        redacted, findings = redact_secrets(text)
        assert f"[REDACTED:{kind}]" in redacted
        assert findings and findings[0].startswith(kind)

    def test_clean_text_untouched(self) -> None:
        text = "The battery lasts ten hours [1]."
        redacted, findings = redact_secrets(text)
        assert redacted == text
        assert findings == []

    def test_fake_placeholders_survive(self) -> None:
        text = "Set YOUR_API_KEY in the environment before use."
        redacted, findings = redact_secrets(text)
        assert redacted == text
        assert findings == []


class TestGuardOutput:
    async def test_toxicity_blocks(self) -> None:
        engine = _FakeEngine({"output_toxicity": _answer(0.93)})
        result = await guard_output(engine, run_id="r", text="something awful")
        assert result.blocked is True

    async def test_below_threshold_passes_and_redacts(self) -> None:
        engine = _FakeEngine({"output_toxicity": _answer(0.1), "output_secrets": _answer(0.9)})
        result = await guard_output(engine, run_id="r", text="contact admin@corp.example.com")
        assert result.blocked is False
        assert "[REDACTED:EMAIL]" in result.redacted_text
        assert "admin@corp.example.com" not in result.redacted_text

    async def test_jev_flags_leak_without_regex_match_still_unredacted(self) -> None:
        engine = _FakeEngine({"output_toxicity": _answer(0.0), "output_secrets": _answer(0.95)})
        result = await guard_output(engine, run_id="r", text="nothing findable here")
        assert result.blocked is False
        assert result.redacted_text == "nothing findable here"

    async def test_empty_text_short_circuits(self) -> None:
        engine = _FakeEngine({})
        result = await guard_output(engine, run_id="r", text="  ")
        assert result.blocked is False
        assert engine.calls == []
