"""DecisionEngine wire types (TRD §8).

`Question` is a discriminated union of `Noul` (yes-probability), `Choice`
(options with criteria) and `Score` (numeric range) — mirroring Jev's
three question types. `Answer` carries the chosen value plus provenance
(engine, latency_ms) for the SSE decision event and trace panel.

Thresholds are *not* baked into the Question classes; per-engine values
live in `decisions/thresholds.py` so a fallback probability of 0.7 is not
treated as a Jev 0.7 (TRD §8 switching rules).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Noul(BaseModel):
    """Yes/no question answered as a probability."""

    type: Literal["noul"] = "noul"
    prompt: str


class Choice(BaseModel):
    """Pick one of `options`; `criteria` describes the basis for the pick."""

    type: Literal["choice"] = "choice"
    prompt: str
    options: list[str] = Field(min_length=2)
    criteria: str = ""


class Score(BaseModel):
    """Numeric score in [min, max]."""

    type: Literal["score"] = "score"
    prompt: str
    min: float = 0.0
    max: float = 1.0


Question = Annotated[Noul | Choice | Score, Field(discriminator="type")]


class Answer(BaseModel):
    """One question's outcome plus engine provenance (TRD §12 decision event)."""

    engine: Literal["jev", "fallback"]
    latency_ms: int
    # Noul: yes-probability. Choice: argmax value + full probability map.
    # Score: numeric value in the question's range.
    value: str | float
    probability: float | None = None
    probabilities: dict[str, float] | None = None
    reasoning: str | None = None
