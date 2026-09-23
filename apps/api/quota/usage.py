from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import get_settings
from db.models import Model, UsageLedger
from quota.service import UsageSnapshot, calculate_credits


@dataclass
class UsageContext:
    session_factory: async_sessionmaker[AsyncSession]
    user_id: UUID
    run_id: UUID
    model_roles: dict[str, str]
    api_keys: dict[str, str] = field(default_factory=dict)
    remaining_5h: float | None = None
    reference_model_id: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    credits: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _last_model: str = field(default="aggregate", repr=False)
    _prices: dict[str, tuple[float, float]] = field(default_factory=dict)
    _reference_price: float | None = field(default=None, repr=False)

    async def resolve_model(self, requested: str, role: str) -> str:
        return self.model_roles.get(role, requested)

    def api_key_for(self, model: str) -> str | None:
        return self.api_keys.get(model) or self.api_keys.get(model.removeprefix("openrouter/"))

    async def record_call(
        self, *, model_id: str, role: str, tokens_in: int, tokens_out: int
    ) -> float:
        async with self._lock:
            model = await self.resolve_model(model_id, role)
            catalogue_id = model.removeprefix("openrouter/")
            self._last_model = catalogue_id
            async with self.session_factory() as session:
                prices = await self._load_prices(session, catalogue_id)
                reference = await self._load_reference_price(session)
            value = calculate_credits(
                price_in=prices[0],
                price_out=prices[1],
                reference_price=reference,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            if role != "async_judge":
                self.tokens_in += max(0, tokens_in)
                self.tokens_out += max(0, tokens_out)
                self.credits += value
            async with self.session_factory() as session, session.begin():
                aggregate = (
                    await session.execute(
                        select(UsageLedger)
                        .where(UsageLedger.run_id == self.run_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if role == "async_judge":
                    if aggregate is not None:
                        session.add(
                            UsageLedger(
                                user_id=self.user_id,
                                run_id=self.run_id,
                                model=self._last_model,
                                role=role,
                                tokens_in=max(0, tokens_in),
                                tokens_out=max(0, tokens_out),
                                credits=value,
                                status="settled",
                                ts=datetime.now(UTC),
                            )
                        )
                elif aggregate is not None:
                    aggregate.model = self._last_model
                    aggregate.role = "run"
                    aggregate.tokens_in = self.tokens_in
                    aggregate.tokens_out = self.tokens_out
                    aggregate.credits = self.credits
            return value

    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            model="aggregate",
            role="run",
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            credits=self.credits,
        )

    async def _load_prices(self, session: AsyncSession, model_id: str) -> tuple[float, float]:
        if model_id in self._prices:
            return self._prices[model_id]
        row = (
            await session.execute(
                select(Model.price_in, Model.price_out).where(Model.model_id == model_id)
            )
        ).first()
        if row is None and "/" in model_id:
            row = (
                await session.execute(
                    select(Model.price_in, Model.price_out).where(
                        Model.model_id == model_id.split("/", 1)[1]
                    )
                )
            ).first()
        prices = (
            (
                float(row[0]) if row and row[0] is not None else 0.0,
                float(row[1]) if row and row[1] is not None else 0.0,
            )
            if row is not None
            else (0.0, 0.0)
        )
        self._prices[model_id] = prices
        return prices

    async def _load_reference_price(self, session: AsyncSession) -> float:
        if self._reference_price is not None:
            return self._reference_price
        reference_model_id = self.reference_model_id or get_settings().reference_model_id
        row = (
            await session.execute(
                select(Model.price_in).where(Model.model_id == reference_model_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await session.execute(
                    select(Model.price_in)
                    .where(Model.model_id.ilike("%haiku%"))
                    .order_by(Model.model_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
        self._reference_price = float(row) if row is not None and float(row) > 0 else 1.0
        return self._reference_price


_usage_context: ContextVar[UsageContext | None] = ContextVar(
    "veriforge_usage_context", default=None
)


def get_usage_context() -> UsageContext | None:
    return _usage_context.get()


def set_usage_context(context: UsageContext) -> Token[UsageContext | None]:
    return _usage_context.set(context)


def reset_usage_context(token: Token[UsageContext | None]) -> None:
    _usage_context.reset(token)
