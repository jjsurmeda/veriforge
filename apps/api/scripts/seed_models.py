"""Seed the model catalogue and role bindings with free OpenRouter models.

Every LLM call except Jev runs on a `:free` OpenRouter id, so the corpus can
be demoed without a paid key. The catalogue is read live from
`GET /api/v1/models` and filtered to ids whose prompt and completion prices are
both 0, so a rerun after OpenRouter rotates its free pool is just a rerun.

Free ids churn. Nothing outside config defaults and this script hardcodes one:
the picks live in PREFERRED below and are re-resolved against the catalogue on
every run, so a retired id falls back to the next best free model.

Usage: `uv run python scripts/seed_models.py` (or `make seed-models`).
"""

import asyncio
import json
import sys
import urllib.request
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import LlmProvider, Model, ModelRole
from db.session import get_session_factory

CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
PROVIDER_NAME = "openrouter"

JEV_MODEL_ID = "typesafe/jev-1.13"

STRONG: list[str] = ["nvidia/nemotron-3-super-120b-a12b:free"]
SMALL: list[str] = ["nvidia/nemotron-3.5-lightning:free"]

# Each entry is (role, tier, [candidate ids], context floor). Chosen 2026-09-26
# from the 17 free ids OpenRouter listed that day: a 120B-class MoE for the
# strong tier, a fast one for the small tier. When a preferred id retires the
# tier falls back within itself, and the strong tier never lands on the model
# the small tier already took.
ROLES: list[tuple[str, str, list[str], int]] = [
    ("generator", "strong", STRONG, 32_000),
    ("planner", "strong", STRONG, 32_000),
    ("decision_fallback", "strong", STRONG, 32_000),
    ("small", "small", SMALL, 32_000),
    ("titler", "small", SMALL, 8_000),
    ("rewriter", "small", SMALL, 8_000),
    ("suggester", "small", SMALL, 8_000),
    ("claim_extractor", "small", SMALL, 8_000),
]

EXTRA_PREFERRED = [
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
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
    exclude: frozenset[str] = frozenset(),
) -> str | None:
    for model_id in candidates:
        entry = catalogue.get(model_id)
        if entry is not None and entry["context_window"] >= floor and model_id not in exclude:
            return model_id
    usable = sorted(
        (
            (entry["context_window"], model_id)
            for model_id, entry in catalogue.items()
            if entry["context_window"] >= floor and model_id not in exclude
        ),
        reverse=True,
    )
    return usable[0][1] if usable else None


def _strong_tier_exclude(tier: str, small_tier: str | None) -> frozenset[str]:
    if tier != "strong" or small_tier is None:
        return frozenset()
    return frozenset({small_tier})


async def seed(catalogue: dict[str, FreeModel] | None = None) -> None:
    catalogue = fetch_catalogue() if catalogue is None else catalogue
    print(f"catalogue: {len(catalogue)} free models on OpenRouter")

    wanted: dict[str, FreeModel] = {JEV_MODEL_ID: {"context_window": 32_768, "name": "Jev"}}
    # Small roles pick first so the strong tier can exclude whatever they took;
    # otherwise a retired small id would also become the generator.
    small_tier = pick(catalogue, SMALL, 32_000)
    for role, tier, candidates, floor in sorted(ROLES, key=lambda row: row[3]):
        exclude = _strong_tier_exclude(tier, small_tier)
        chosen = pick(catalogue, candidates, floor, exclude)
        if chosen is None:
            raise SystemExit(f"no free model with a {floor}-token window for role {role}")
        wanted[chosen] = catalogue[chosen]
        print(f"  {role:<16} {chosen}")
    for model_id in EXTRA_PREFERRED:
        if model_id in catalogue and model_id not in wanted:
            wanted[model_id] = catalogue[model_id]

    factory = get_session_factory()
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

        for role, _tier, candidates, floor in sorted(ROLES, key=lambda row: row[3]):
            exclude = _strong_tier_exclude(_tier, small_tier)
            chosen = pick(catalogue, candidates, floor, exclude)
            if chosen is None:
                raise SystemExit(f"no free model with a {floor}-token window for role {role}")
            await session.execute(
                pg_insert(ModelRole)
                .values(role=role, model_id=chosen)
                .on_conflict_do_update(index_elements=[ModelRole.role], set_={"model_id": chosen})
            )

    print(f"seeded {len(wanted)} models and {len(ROLES)} role bindings")


if __name__ == "__main__":
    asyncio.run(seed())
