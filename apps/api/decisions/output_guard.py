"""Output guardrail (TRD §10 "in parallel with review", TRD §11): Jev
`output_toxicity` Noul (block ≥ 0.85) plus a regex + Jev check for
leaked secrets/PII in the generated output — distinct from slice 4's
ingress guard on the *user's* message.

Redaction policy (the format slice 4 deferred here): every regex match is
substituted with `[REDACTED:<KIND>]` — EMAIL, CREDIT_CARD, API_KEY,
PRIVATE_KEY, SECRET. Phone numbers are deliberately not matched (too
many false positives on order numbers and dates); the Jev `output_secrets`
check catches residual leaks we cannot locate — when it fires without a
regex match we log and surface the decision event but cannot substitute,
so nothing is rewritten blind.
"""

import logging
import re
from dataclasses import dataclass, field

from decisions import threshold
from decisions.engine import EngineProtocol
from schemas.decisions import Answer, Noul

logger = logging.getLogger(__name__)

TOXICITY_QUESTION = "output_toxicity"
SECRETS_QUESTION = "output_secrets"

_REDACTIONS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "API_KEY",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}"
            r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})\b"
        ),
    ),
    (
        "CREDIT_CARD",
        re.compile(r"\b\d{4}[ -]?\d{6}[ -]?\d{5}\b|\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b"),
    ),
    (
        "SECRET",
        re.compile(
            r"\b(?i:api[_-]?key|secret|token|password)\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{16,}[\"']?"
        ),
    ),
]


@dataclass
class OutputGuardResult:
    blocked: bool = False
    redacted_text: str = ""
    toxicity_answer: Answer | None = None
    secrets_answer: Answer | None = None
    findings: list[str] = field(default_factory=list)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    findings: list[str] = []
    for kind, pattern in _REDACTIONS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        if n:
            findings.append(f"{kind}x{n}")
    return text, findings


def _secrets_noul(text: str) -> Noul:
    return Noul(
        prompt=(
            "Does the following assistant output contain leaked secrets or "
            "personal data — API keys, passwords, tokens, private keys, "
            "email addresses, credit-card numbers — that the assistant was "
            "not supposed to repeat? Code examples with obviously fake "
            "placeholders (e.g. YOUR_API_KEY) do not count. Answer yes only "
            "for what looks like a real secret or real personal data.\n\n"
            f"[output]\n{text[:6000]}"
        )
    )


async def guard_output(engine: EngineProtocol, *, run_id: str, text: str) -> OutputGuardResult:
    result = OutputGuardResult(redacted_text=text)
    if not text.strip():
        return result

    answers = await engine.decide(
        state={"run_id": run_id, "kind": "output_guard"},
        questions={
            TOXICITY_QUESTION: Noul(
                prompt=(
                    "Is the following assistant output toxic — harassment, "
                    "hate speech, graphic incitement? Answer yes only for "
                    "text that must not be delivered to the user.\n\n"
                    f"[output]\n{text[:6000]}"
                )
            ),
            SECRETS_QUESTION: _secrets_noul(text),
        },
    )
    toxicity = answers.get(TOXICITY_QUESTION)
    secrets = answers.get(SECRETS_QUESTION)
    result.toxicity_answer = toxicity
    result.secrets_answer = secrets

    if toxicity is not None:
        block_threshold = threshold("output_toxicity_block", toxicity.engine)
        if float(toxicity.value) >= block_threshold:
            result.blocked = True
            logger.warning(
                "output guard blocked text (p=%.3f, engine=%s)",
                float(toxicity.value),
                toxicity.engine,
            )
            return result

    redacted, findings = redact_secrets(text)
    result.redacted_text = redacted
    result.findings = findings
    if secrets is not None:
        secrets_p = float(secrets.value)
        warn_threshold = threshold("guard_pii_warn", secrets.engine)
        if findings:
            logger.info("output redacted %s (jev_secrets_p=%.2f)", findings, secrets_p)
        elif secrets_p >= warn_threshold:
            # Jev sees a leak the regexes cannot locate — surface it, never
            # rewrite blind (see module docstring).
            logger.warning(
                "output guard: Jev flags possible leak (p=%.2f) with no "
                "regex match; emitting unredacted",
                secrets_p,
            )
    return result
