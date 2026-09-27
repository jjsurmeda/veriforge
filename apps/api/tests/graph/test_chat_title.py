from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat
from graph.chat_title import (
    collapse_instant_title,
    generate_chat_title,
    parse_chat_title,
    refine_chat_title,
)


def test_collapse_instant_title_truncates_at_word_boundary() -> None:
    question = (
        "  Explain   adaptive retrieval with citations and reviewer confidence "
        "scoring please  "
    )

    title = collapse_instant_title(question)

    assert title == "Explain adaptive retrieval with citations and reviewer…"
    assert len(title) <= 60


def test_parse_chat_title_accepts_fenced_json() -> None:
    assert parse_chat_title('```json\n{"title": "Adaptive Retrieval Flow"}\n```') == (
        "Adaptive Retrieval Flow"
    )


async def test_generate_chat_title_falls_back_on_llm_failure() -> None:
    async def failing_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        raise RuntimeError("boom")

    assert (
        await generate_chat_title(
            question="How does adaptive retrieval work?",
            answer="It rewrites, retrieves, reviews, and answers.",
            small_model="openrouter/small",
            complete_fn=failing_complete,
        )
        is None
    )


async def test_refine_writes_a_topic_title(db: AsyncSession) -> None:
    from tests.retrieval.conftest import make_user

    user = await make_user(db, "title-a@test.dev")
    chat = Chat(user_id=user.id, title="What does Mr. Darcy say in his first proposal?")
    db.add(chat)
    await db.commit()

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return '{"title": "Darcy\'s first proposal"}'

    title = await refine_chat_title(
        session=db,
        chat_id=chat.id,
        instant_title=chat.title,
        question="What does Mr. Darcy say in his first proposal?",
        answer="He proposes.",
        small_model="openrouter/small",
        complete_fn=fake_complete,
    )

    assert title == "Darcy's first proposal"
    assert chat.title == "Darcy's first proposal"


async def test_refine_titles_the_first_grounded_turn_after_chitchat(db: AsyncSession) -> None:
    from tests.retrieval.conftest import make_user

    user = await make_user(db, "title-after-chitchat@test.dev")
    chat = Chat(user_id=user.id, title="hello")
    db.add(chat)
    await db.commit()

    await refine_chat_title(
        session=db,
        chat_id=chat.id,
        instant_title="hello",
        question="hello",
        answer="Hello!",
        small_model="openrouter/small",
        chitchat=True,
    )
    assert chat.title == "New chat"

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return '{"title": "Darcy\'s first proposal"}'

    title = await refine_chat_title(
        session=db,
        chat_id=chat.id,
        instant_title=None,
        question="What does Darcy say in his first proposal?",
        answer="He proposes.",
        small_model="openrouter/small",
        complete_fn=fake_complete,
    )

    assert title == "Darcy's first proposal"
    assert chat.title == "Darcy's first proposal"


async def test_refine_skips_a_user_renamed_chat(db: AsyncSession) -> None:
    from tests.retrieval.conftest import make_user

    user = await make_user(db, "title-b@test.dev")
    chat = Chat(user_id=user.id, title="My saved title")
    db.add(chat)
    await db.commit()

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        return '{"title": "Should not win"}'

    title = await refine_chat_title(
        session=db,
        chat_id=chat.id,
        instant_title="What does Mr. Darcy say in his first proposal?",
        question="q",
        answer="a",
        small_model="openrouter/small",
        complete_fn=fake_complete,
    )

    assert title is None
    assert chat.title == "My saved title"


async def test_chitchat_first_turn_keeps_new_chat(db: AsyncSession) -> None:
    from tests.retrieval.conftest import make_user

    user = await make_user(db, "title-c@test.dev")
    chat = Chat(user_id=user.id, title="hi there how's it going")
    db.add(chat)
    await db.commit()

    called = False

    async def fake_complete(
        *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
    ) -> str:
        nonlocal called
        called = True
        return '{"title": "Should not be used"}'

    title = await refine_chat_title(
        session=db,
        chat_id=chat.id,
        instant_title="hi there how's it going",
        question="hi there how's it going",
        answer="Hey!",
        small_model="openrouter/small",
        complete_fn=fake_complete,
        chitchat=True,
    )

    assert title == "New chat"
    assert called is False
    assert chat.title == "New chat"
