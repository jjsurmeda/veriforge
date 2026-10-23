"""The api, with a measurement wrapper around the two decision engines (R3 shadow).

Measurement only: nothing in the product changes. This launcher imports the
app in-process, wraps `JevClient.decide`, `FallbackEngine.decide`,
`DecisionEngine._shadow_compare` and `litellm.acompletion` at class/module
level, then serves `main:app` with uvicorn. In-process matters: the
generation-stats seam (`evals.attribution`, the Jev `generation_id_sink`) only
sees calls made in the process that installed it, which is why a separately
started api could not be costed.

Every engine call and every LLM call is appended as one JSON line to
`$SHADOW_CALL_LOG`:

- `type=call`: one `decide()` batch by one engine. `engine` is `jev` or
  `judge` (the fallback), `shadow` says the judge call was the sampled
  double-check, `pair` ties a judge call to the Jev call it shadowed,
  `areas` the question-key prefixes, `wall_ms`, and `answers` (value and
  probabilities per key, so rerank passages and pairs replay without the DB).
- `type=gen`: one provider generation id (litellm `x-generation-id` header,
  or the Jev sink), with the `call` it belongs to when it was made inside a
  decide batch, plus whatever `usage` / `response_cost` litellm returned.
  `scripts/shadow_resolve.py` turns the ids into tokens and real USD.

Run from `apps/api`: `python -m scripts.shadow_api`. Port `$SHADOW_PORT`
(default 8123).
"""

import contextvars
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litellm
import uvicorn

from decisions import jev as jev_mod
from decisions.engine import DecisionEngine
from decisions.fallback import FallbackEngine
from decisions.jev import JevClient

LOG = Path(os.environ.get("SHADOW_CALL_LOG", ".data/shadow-calls.jsonl"))
_lock = threading.Lock()
CALL: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("call", default=None)
SHADOW: contextvars.ContextVar[bool] = contextvars.ContextVar("shadow", default=False)
PAIR: contextvars.ContextVar[str | None] = contextvars.ContextVar("pair", default=None)


def _emit(rec: dict[str, Any]) -> None:
    line = json.dumps(rec, default=str)
    with _lock, LOG.open("a") as fh:
        fh.write(line + "\n")


def _area(key: str) -> str:
    """`passage_12` -> `passage`, `entity_0_1` -> `entity`, `c3` -> `c`."""
    head = key.rstrip("0123456789_")
    return head or key


def _answers(answers: dict[str, Any]) -> dict[str, Any]:
    return {
        k: {"value": a.value, "p": a.probability, "probs": a.probabilities}
        for k, a in answers.items()
    }


def _wrap_decide(cls: Any, engine: str) -> None:
    original = cls.decide

    async def decide(self: Any, *, state: Any, questions: dict[str, Any]) -> Any:
        stage = state.get("kind") if isinstance(state, dict) else None
        run_id = state.get("run_id") if isinstance(state, dict) else None
        rec: dict[str, Any] = {
            "type": "call",
            "call": uuid.uuid4().hex[:12],
            "engine": engine,
            "shadow": engine == "judge" and SHADOW.get(),
            "pair": PAIR.get() if engine == "judge" and SHADOW.get() else None,
            "stage": stage,
            "run_id": str(run_id) if run_id is not None else None,
            "batch": len(questions),
            "keys": list(questions),
            "areas": sorted({_area(k) for k in questions}),
            "ts": time.time(),
        }
        # Rerank questions embed the passage; a digest of it (and the query)
        # lets the passage index map to a chunk id afterwards.
        prompts = {k: getattr(q, "prompt", "") for k, q in questions.items()}
        if stage == "rerank" and prompts:
            rec["pdig"] = {
                k: hashlib.sha1(
                    p.split("[Passage]\n", 1)[-1].encode(), usedforsecurity=False
                ).hexdigest()[:12]
                for k, p in prompts.items()
            }
            first = next(iter(prompts.values()))
            rec["query"] = first.split("[Question]\n", 1)[-1].split("\n\n[Passage]", 1)[0]
        token = CALL.set(rec)
        started = time.monotonic()
        try:
            answers = await original(self, state=state, questions=questions)
        except BaseException as exc:
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            raise
        else:
            rec["answers"] = _answers(answers)
            return answers
        finally:
            rec["wall_ms"] = round((time.monotonic() - started) * 1000)
            CALL.reset(token)
            _emit(rec)
            if engine == "jev" and "error" not in rec:
                # Left set on purpose: the shadow task is created later in this
                # same context and copies it, which is how the judge call finds
                # the Jev call it double-checks.
                PAIR.set(rec["call"])

    cls.decide = decide


def _wrap_shadow() -> None:
    original = DecisionEngine._shadow_compare

    async def shadow_compare(self: Any, *args: Any, **kwargs: Any) -> None:
        SHADOW.set(True)
        await original(self, *args, **kwargs)

    DecisionEngine._shadow_compare = shadow_compare  # type: ignore[method-assign]


def _wrap_usage() -> None:
    """A shadow judge call that finishes after its run has settled fails in
    `UsageContext.record_call` (`scalar_one_or_none` finds the run row plus the
    `async_judge` ledger rows: MultipleResultsFound) AFTER the provider has
    answered and billed, so the pair is lost. Swallow that error for shadow
    calls only; the measurement keeps the answer. Product code is untouched."""
    from quota.usage import UsageContext

    original = UsageContext.record_call

    async def record_call(self: Any, **kwargs: Any) -> Any:
        try:
            return await original(self, **kwargs)
        except Exception as exc:
            if not SHADOW.get():
                raise
            _emit({"type": "usage_error", "err": type(exc).__name__, "ts": time.time()})
            return 0.0

    UsageContext.record_call = record_call  # type: ignore[method-assign]


def _wrap_litellm() -> None:
    original = litellm.acompletion

    async def acompletion(**kwargs: Any) -> Any:
        started = time.monotonic()
        response = await original(**kwargs)
        meta = kwargs.get("metadata") or {}
        headers = getattr(response, "_response_headers", None) or {}
        call = CALL.get()
        usage = getattr(response, "usage", None)
        hidden = getattr(response, "_hidden_params", None) or {}
        _emit(
            {
                "type": "gen",
                "source": "litellm",
                "id": headers.get("x-generation-id"),
                "model": str(kwargs.get("model", "")),
                "role": meta.get("role"),
                "run_id": meta.get("run_id") or (call or {}).get("run_id"),
                "call": (call or {}).get("call"),
                "stream": bool(kwargs.get("stream")),
                "open_ms": round((time.monotonic() - started) * 1000),
                "usage": usage.model_dump() if usage is not None else None,
                "response_cost": hidden.get("response_cost"),
                "ts": time.time(),
            }
        )
        return response

    litellm.acompletion = acompletion


def _jev_sink(generation_id: str) -> None:
    call = CALL.get() or {}
    _emit(
        {
            "type": "gen",
            "source": "jev",
            "id": generation_id,
            "role": "decision_engine",
            "run_id": call.get("run_id"),
            "call": call.get("call"),
            "ts": time.time(),
        }
    )


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    _wrap_decide(JevClient, "jev")
    _wrap_decide(FallbackEngine, "judge")
    _wrap_shadow()
    _wrap_litellm()
    _wrap_usage()
    jev_mod.generation_id_sink = _jev_sink
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.environ.get("SHADOW_PORT", "8123")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
