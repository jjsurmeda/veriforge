"""DecisionEngine package (TRD §8).

Public surface: `DecisionEngine`, `JevClient`, `FallbackEngine`,
`CircuitBreaker`, `threshold`. The graph never imports anything else.
"""

from decisions.breaker import BreakerState, CircuitBreaker
from decisions.engine import DecisionEngine, EngineMode
from decisions.fallback import FallbackEngine
from decisions.jev import JevClient
from decisions.shadow import make_shadow_writer
from decisions.thresholds import threshold

__all__ = [
    "BreakerState",
    "CircuitBreaker",
    "DecisionEngine",
    "EngineMode",
    "FallbackEngine",
    "JevClient",
    "make_shadow_writer",
    "threshold",
]
