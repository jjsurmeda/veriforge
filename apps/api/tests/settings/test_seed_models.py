"""The model seed must be safe to rerun and must leave every non-Jev role on a
free model. No network: the catalogue is passed in (testing.md)."""

from sqlalchemy import select

from db.models import LlmProvider, Model, ModelRole
from db.session import get_session_factory
from scripts.seed_models import ROLES, FreeModel, pick, seed

JEV = "typesafe/jev-1.13"

CATALOGUE: dict[str, FreeModel] = {
    "nvidia/nemotron-3-super-120b-a12b:free": {
        "context_window": 262_144,
        "name": "Nemotron 3 Super",
    },
    "nvidia/nemotron-3-ultra-550b-a55b:free": {
        "context_window": 1_000_000,
        "name": "Nemotron 3 Ultra",
    },
    "some/paid-model": {"context_window": 200_000, "name": "Paid"},
}


async def test_seed_is_idempotent() -> None:
    factory = get_session_factory()
    await seed(CATALOGUE)
    async with factory() as session:
        first = (
            await session.execute(
                select(Model.model_id, Model.price_in, Model.price_out, Model.context_window)
            )
        ).all()
        roles_first = (await session.execute(select(ModelRole.role, ModelRole.model_id))).all()

    await seed(CATALOGUE)
    async with factory() as session:
        second = (
            await session.execute(
                select(Model.model_id, Model.price_in, Model.price_out, Model.context_window)
            )
        ).all()
        roles_second = (await session.execute(select(ModelRole.role, ModelRole.model_id))).all()

    assert sorted(first) == sorted(second)
    assert sorted(roles_first) == sorted(roles_second)
    seeded = {model_id for model_id, *_rest in first if model_id.endswith(":free")}
    assert seeded == {
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
    }


async def test_every_seeded_model_is_free_and_jev_is_untouched() -> None:
    factory = get_session_factory()
    async with factory() as session:
        before = (
            await session.execute(
                select(ModelRole.role, ModelRole.model_id).where(
                    ModelRole.role == "decision_engine"
                )
            )
        ).all()

    await seed(CATALOGUE)

    async with factory() as session:
        rows = (
            await session.execute(select(Model.model_id, Model.price_in, Model.price_out))
        ).all()
        after = (
            await session.execute(
                select(ModelRole.role, ModelRole.model_id).where(
                    ModelRole.role == "decision_engine"
                )
            )
        ).all()

    priced = {model_id: (price_in, price_out) for model_id, price_in, price_out in rows}
    for model_id, prices in priced.items():
        if model_id.endswith(":free"):
            assert prices == (0, 0), model_id
    assert "some/paid-model" not in priced
    assert [(role, model_id) for role, model_id in after] == [("decision_engine", JEV)]
    assert [(role, model_id) for role, model_id in before] == [("decision_engine", JEV)]


async def test_role_resolution_returns_a_free_model() -> None:
    await seed(CATALOGUE)
    factory = get_session_factory()
    async with factory() as session:
        role_rows = (await session.execute(select(ModelRole.role, ModelRole.model_id))).all()
        roles = {role: model_id for role, model_id in role_rows}
        provider_rows = (await session.execute(select(LlmProvider.name, LlmProvider.kind))).all()
        providers = {name: kind for name, kind in provider_rows}
    for role, _tier, _candidates, _floor in ROLES:
        assert roles[role].endswith(":free"), role
    assert roles["generator"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert roles["small"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert roles["planner"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert roles["claim_extractor"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert providers["openrouter"] == "openrouter"


def test_pick_falls_back_when_the_preferred_id_is_gone() -> None:
    preferred = "nvidia/nemotron-3-super-120b-a12b:free"
    assert pick(CATALOGUE, [preferred], 8_000) == preferred
    retired = {k: v for k, v in CATALOGUE.items() if "nemotron-3-super" not in k}
    assert pick(retired, [preferred], 8_000) == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert pick(retired, ["nope:free"], 8_000) == "nvidia/nemotron-3-ultra-550b-a55b:free"
