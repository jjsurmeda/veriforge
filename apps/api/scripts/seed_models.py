"""Seed the model catalogue and the role bindings with the one paid model the
product runs on, `openai/gpt-4o-mini`.

Every non-Jev LLM call runs on `DEFAULT_MODEL_ID`. That is not only a cost
decision: the eval baselines were measured on it, and `evals.gate` refuses to
compare runs whose models differ, so a fresh database that reached a `:free`
id answered questions the gate could not judge at all. It spends credit.

`--free` (or `SEED_MODELS_FREE=1`) seeds OpenRouter's free pool instead — for
local experiments and demos only. It fetches the catalogue live from
`GET /api/v1/models` and keeps ids whose prompt and completion prices are both
0, so a rerun after OpenRouter rotates its free pool is just a rerun. Free ids
churn; nothing outside this script hardcodes one, so a retired id falls back to
the next best free model. A production deployment refuses to boot with a free
binding (`main.assert_no_free_models`), so this path cannot reach it.

`--override-model` (or `SEED_MODELS_OVERRIDE`) points every non-Jev role at
another already-`models`-enabled id. It was added 2026-09-29 (wave 1,
KI-17/KI-2) as a TEMPORARY escape from the unreliable free tier, and that
escape is now the default: reliability outranked cost, and the eval baseline
made the choice explicit.

Usage: `uv run python scripts/seed_models.py` (or `make seed-models`).
"""

import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import DEFAULT_MODEL_ID
from db.models import LlmProvider, Model, ModelRole
from db.session import get_session_factory

CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
PROVIDER_NAME = "openrouter"

JEV_MODEL_ID = "typesafe/jev-1.13"

SUPER = "nvidia/nemotron-3-super-120b-a12b:free"
ULTRA = "nvidia/nemotron-3-ultra-550b-a55b:free"
FAST: list[str] = [SUPER]
DEEP: list[str] = [ULTRA, SUPER]

# Each entry is (role, tier, [candidate ids], context floor). Chosen by a live
# check on 2026-09-26 (docs/known-issues.md KI-2): Super answered JSON and cited
# tasks cleanly in 1-2 s, Ultra matched it at 4-6 s, and nemotron-3.5-lightning
# spent 50-170 s printing its reasoning, so it is not used. When a preferred id
# retires, pick() falls back to the largest-context free model.
ROLES: list[tuple[str, str, list[str], int]] = [
    ("generator", "fast", FAST, 32_000),
    ("decision_fallback", "fast", FAST, 32_000),
    ("small", "fast", FAST, 32_000),
    ("titler", "fast", FAST, 8_000),
    ("rewriter", "fast", FAST, 8_000),
    ("suggester", "fast", FAST, 8_000),
    ("planner", "deep", DEEP, 32_000),
    ("claim_extractor", "deep", DEEP, 32_000),
]

EXTRA_PREFERRED = [
    SUPER,
    ULTRA,
    "google/gemma-4-31b-it:free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-26b-a4b-it:free",
]


class FreeModel(TypedDict):
    context_window: int
    name: str


def fetch_catalogue() -> dict[str, FreeModel]:
    request = urllib.request.Request(CATALOGUE_URL, headers={"User-Agent": "veriforge-seed"})
    # S310: the URL is a module constant, not caller input.
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    free: dict[str, FreeModel] = {}
    for entry in payload["data"]:
        model_id = str(entry["id"])
        pricing = entry.get("pricing") or {}
        if not model_id.endswith(":free"):
            continue
        if float(pricing.get("prompt") or 0) != 0 or float(pricing.get("completion") or 0) != 0:
            continue
        free[model_id] = {
            "context_window": int(entry.get("context_length") or 0),
            "name": str(entry.get("name") or model_id),
        }
    return free


def pick(
    catalogue: dict[str, FreeModel],
    candidates: list[str],
    floor: int,
) -> str | None:
    for model_id in candidates:
        entry = catalogue.get(model_id)
        if entry is not None and entry["context_window"] >= floor:
            return model_id
    usable = sorted(
        (
            (entry["context_window"], model_id)
            for model_id, entry in catalogue.items()
            if entry["context_window"] >= floor
        ),
        reverse=True,
    )
    return usable[0][1] if usable else None


def resolve_model_id(override: str | None = None, *, free: bool = False) -> str | None:
    """The id every non-Jev role is bound to, or None for the free-pool path.

    One function so the CLI, the tests and `make check-work`'s "no :free
    default" step all read the default from the same place: the default path is
    the paid model the eval baselines were measured with, and `free=True` is
    the local-experiment path.
    """
    if free:
        return None
    return override or DEFAULT_MODEL_ID


async def seed(
    catalogue: dict[str, FreeModel] | None = None,
    override: str | None = None,
    *,
    free: bool = False,
) -> None:
    """Bind every non-Jev role to one model id.

    The default is `DEFAULT_MODEL_ID`, the paid model the eval baselines were
    measured with; `free=True` is the local-experiment path that binds the
    free pool instead. `override` names a third id and is the default's
    parameter, so both paid paths share one implementation.
    """
    factory = get_session_factory()
    model_id = resolve_model_id(override, free=free)

    if model_id is not None:
        async with factory() as session:
            row = (
                await session.execute(
                    select(Model.id).where(Model.model_id == model_id, Model.enabled.is_(True))
                )
            ).scalar_one_or_none()
        if row is None:
            raise SystemExit(
                f"{model_id} is not an enabled row in `models`; seed it before binding roles"
            )
        print(f"every non-Jev role -> {model_id} (free catalogue skipped)")
        async with factory() as session, session.begin():
            for role, _tier, _candidates, _floor in ROLES:
                await session.execute(
                    pg_insert(ModelRole)
                    .values(role=role, model_id=model_id)
                    .on_conflict_do_update(
                        index_elements=[ModelRole.role], set_={"model_id": model_id}
                    )
                )
        print(f"rebound {len(ROLES)} roles; decision_engine untouched")
        return

    catalogue = fetch_catalogue() if catalogue is None else catalogue
    print(f"catalogue: {len(catalogue)} free models on OpenRouter (--free: local only)")

    wanted: dict[str, FreeModel] = {JEV_MODEL_ID: {"context_window": 32_768, "name": "Jev"}}
    for role, _tier, candidates, floor in ROLES:
        chosen = pick(catalogue, candidates, floor)
        if chosen is None:
            raise SystemExit(f"no free model with a {floor}-token window for role {role}")
        wanted[chosen] = catalogue[chosen]
        print(f"  {role:<16} {chosen}")
    for model_id in EXTRA_PREFERRED:
        if model_id in catalogue and model_id not in wanted:
            wanted[model_id] = catalogue[model_id]

    async with factory() as session, session.begin():
        provider = (
            await session.execute(select(LlmProvider).where(LlmProvider.name == PROVIDER_NAME))
        ).scalar_one_or_none()
        if provider is None:
            provider = LlmProvider(name=PROVIDER_NAME, kind=PROVIDER_NAME, enabled=True)
            session.add(provider)
            await session.flush()

        for model_id, entry in sorted(wanted.items()):
            await session.execute(
                pg_insert(Model)
                .values(
                    provider_id=provider.id,
                    model_id=model_id,
                    price_in=0,
                    price_out=0,
                    context_window=entry["context_window"],
                    capabilities={"name": entry["name"], "free": True},
                    enabled=True,
                )
                .on_conflict_do_update(
                    index_elements=[Model.provider_id, Model.model_id],
                    set_={
                        "price_in": 0,
                        "price_out": 0,
                        "context_window": entry["context_window"],
                        "capabilities": {"name": entry["name"], "free": True},
                        "enabled": True,
                    },
                )
            )

        for role, _tier, candidates, floor in ROLES:
            chosen = pick(catalogue, candidates, floor)
            if chosen is None:
                raise SystemExit(f"no free model with a {floor}-token window for role {role}")
            await session.execute(
                pg_insert(ModelRole)
                .values(role=role, model_id=chosen)
                .on_conflict_do_update(index_elements=[ModelRole.role], set_={"model_id": chosen})
            )

    print(f"seeded {len(wanted)} models and {len(ROLES)} role bindings")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--override-model",
        default=os.environ.get("SEED_MODELS_OVERRIDE") or None,
        help=f"bind every non-Jev role to this already-seeded model id "
        f"(default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--free",
        action="store_true",
        default=os.environ.get("SEED_MODELS_FREE") == "1",
        help="bind OpenRouter's free pool instead — local experiments only; "
        "a production deployment refuses to boot with a free binding",
    )
    args = parser.parse_args()
    asyncio.run(seed(override=args.override_model, free=args.free))
