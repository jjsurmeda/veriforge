from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from db.models import Chunk, Collection, Document, ModelRole, Section
from db.session import get_session_factory
from providers.llm import complete

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "starter_questions.md"
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


async def run_starter_questions(collection_id: UUID) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Section.heading_path, Chunk.text)
                .join(Chunk, Chunk.section_id == Section.id)
                .join(Document, Document.id == Chunk.document_id)
                .where(Document.collection_id == collection_id)
                .order_by(Chunk.created_at.desc())
                .limit(12)
            )
        ).all()
        if not rows:
            return
        role = (
            await session.execute(select(ModelRole).where(ModelRole.role == "small"))
        ).scalar_one_or_none()
        if role is None:
            logger.warning("starter questions skipped: no small model role")
            return

    excerpts = "\n\n".join(
        f"{heading}\n{text[:400]}" if heading else text[:400] for heading, text in rows
    )
    response = await complete(
        litellm_model=f"openrouter/{role.model_id}",
        messages=[
            {"role": "system", "content": _starter_prompt()},
            {"role": "user", "content": excerpts},
        ],
        metadata={"job": "starter_questions", "role": "suggester"},
    )
    questions = _parse_questions(response)
    if questions is None:
        logger.warning("starter questions skipped: invalid model response")
        return

    async with session_factory() as session:
        collection = await session.get(Collection, collection_id)
        if collection is not None:
            collection.starter_questions = questions
            await session.commit()


def _starter_prompt() -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def _parse_questions(response: str) -> list[str] | None:
    text = response.strip()
    match = _FENCE_RE.match(text)
    if match is not None:
        text = match.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != 3:
        return None
    if not all(isinstance(question, str) and 0 < len(question) <= 200 for question in questions):
        return None
    return questions
