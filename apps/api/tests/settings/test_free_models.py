"""No `:free` model may be reachable from a default path (phase 1).

Three routes reached a free id, and each one silently ran the product on a
model the eval baseline never saw: the seed's default path, the two config
fallbacks, and a role binding. The gate refuses a cross-model comparison, so
a run that landed on Nemotron was not a regression check, it was no check at
all — and a free tier 429s and may log prompts.

No network and no live provider calls (testing.md): the catalogue fetch is
replaced by a function that fails the test if it is called.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import (
    DEFAULT_MODEL_ID,
    GENERATOR_MODEL_ID,
    Settings,
    free_model_violations,
    is_free_model,
)
from db.models import LlmProvider, Model, ModelRole
from db.session import get_session_factory
from main import assert_no_free_models
from scripts.seed_models import ROLES, seed

FREE_MODEL_ID = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"


def _settings(**overrides: object) -> Settings:
    """The settings a fresh deployment boots with, with `overrides` applied.

    `_env_file=None`: this is about the *defaults*, not about whatever the
    developer's .env happens to say.
    """
    return Settings(_env_file=None).model_copy(update=overrides)


def _paid_bindings() -> dict[str, str]:
    return {role: DEFAULT_MODEL_ID for role, *_rest in ROLES}


def _refusing_fetch() -> dict[str, object]:
    raise AssertionError("the default seed path fetched the free catalogue")


def test_is_free_model_reads_the_suffix_and_the_free_router() -> None:
    assert is_free_model(FREE_MODEL_ID)
    assert is_free_model("openrouter/openrouter/free")
    assert not is_free_model("openrouter/openai/gpt-4o-mini")
    assert not is_free_model(DEFAULT_MODEL_ID)


def test_config_defaults_name_no_free_model() -> None:
    settings = _settings()
    assert not is_free_model(settings.fallback_model), settings.fallback_model
    assert not is_free_model(settings.llm_fallback_model), settings.llm_fallback_model
    assert settings.fallback_model == f"openrouter/{DEFAULT_MODEL_ID}"
    assert settings.llm_fallback_model == f"openrouter/{DEFAULT_MODEL_ID}"


async def test_seed_default_leaves_no_role_on_a_free_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default path, on a real database: every non-Jev role is the paid
    model, so a fresh database is not one `:free` fallback away."""
    monkeypatch.setattr("scripts.seed_models.fetch_catalogue", _refusing_fetch)

    await seed()

    async with get_session_factory()() as session:
        roles = {
            role: model_id
            for role, model_id in (
                await session.execute(select(ModelRole.role, ModelRole.model_id))
            ).all()
        }
        free_rows = (
            await session.execute(select(Model.model_id).where(Model.model_id.like("%:free")))
        ).scalars().all()

    assert free_rows == []
    for role, _tier, _candidates, _floor in ROLES:
        expected = GENERATOR_MODEL_ID if role == "generator" else DEFAULT_MODEL_ID
        assert roles[role] == expected, role
    assert roles["decision_engine"] == "typesafe/jev-1.13"


async def test_seed_binds_the_generator_to_deepseek_with_its_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-007: the generator row exists, is enabled and carries the pinned price;
    a rerun is idempotent."""
    monkeypatch.setattr("scripts.seed_models.fetch_catalogue", _refusing_fetch)

    await seed()
    await seed()

    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(Model.price_in, Model.price_out, Model.enabled).where(
                    Model.model_id == GENERATOR_MODEL_ID
                )
            )
        ).one()
    assert float(row.price_in) == pytest.approx(0.4427)
    assert float(row.price_out) == pytest.approx(0.8853)
    assert row.enabled is True


async def _bind_generator_to_a_free_model() -> None:
    async with get_session_factory()() as session, session.begin():
        provider = (
            await session.execute(select(LlmProvider).where(LlmProvider.name == "openrouter"))
        ).scalar_one()
        session.add(
            Model(
                provider_id=provider.id,
                model_id=FREE_MODEL_ID,
                price_in=0,
                price_out=0,
                context_window=262_144,
                capabilities={"free": True},
                enabled=True,
            )
        )
        await session.flush()
        await session.execute(
            pg_insert(ModelRole)
            .values(role="generator", model_id=FREE_MODEL_ID)
            .on_conflict_do_update(
                index_elements=[ModelRole.role], set_={"model_id": FREE_MODEL_ID}
            )
        )


def test_production_check_accepts_gpt_4o_mini_bindings() -> None:
    settings = _settings(environment="production")
    assert free_model_violations(settings, _paid_bindings()) == []


def test_production_check_names_a_free_role_binding() -> None:
    settings = _settings(environment="production")
    bindings = _paid_bindings() | {"generator": FREE_MODEL_ID}

    violations = free_model_violations(settings, bindings)

    assert len(violations) == 1
    assert "generator" in violations[0]
    assert ":free" in violations[0]


def test_production_check_names_a_free_fallback() -> None:
    settings = _settings(llm_fallback_model="openrouter/openrouter/free")

    violations = free_model_violations(settings, {})

    assert len(violations) == 1
    assert "llm_fallback_model" in violations[0]


async def test_production_boot_refuses_a_seeded_free_binding() -> None:
    """The check as boot runs it: the role bindings are read from the
    database, not from a mapping this test wrote."""
    await seed()
    await _bind_generator_to_a_free_model()

    with pytest.raises(RuntimeError) as excinfo:
        await assert_no_free_models(get_session_factory(), _settings(environment="production"))

    assert "generator" in str(excinfo.value)
    assert ":free" in str(excinfo.value)


async def test_production_boot_accepts_the_paid_seeded_roles() -> None:
    await seed()

    await assert_no_free_models(get_session_factory(), _settings(environment="production"))