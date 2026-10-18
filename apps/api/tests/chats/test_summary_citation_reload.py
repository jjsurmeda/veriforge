"""A summary citation keeps its evidence after a reload (third-party review #2).

A summary is not a row of `chunks`, so its citation has no chunk and the messages
endpoint used to return null document name, excerpt and document id for it."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, Citation, Message, User
from tests.retrieval.conftest import make_collection, make_document, make_section


async def test_a_chunkless_citation_resolves_through_its_own_document_and_excerpt(
    client: AsyncClient, db: AsyncSession
) -> None:
    signup = await client.post(
        "/auth/signup", json={"email": "summary@test.dev", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    user = (await db.execute(select(User).where(User.email == "summary@test.dev"))).scalar_one()
    collection = await make_collection(db, user, "books")
    document = await make_document(db, collection, "Dracula.txt")
    section = await make_section(db, document)

    chat = Chat(user_id=user.id, title="t")
    db.add(chat)
    await db.flush()
    message = Message(
        chat_id=chat.id, role="assistant", content="A summary [1].", status="complete"
    )
    db.add(message)
    await db.flush()
    db.add(
        Citation(
            message_id=message.id,
            n=1,
            chunk_id=None,
            document_id=document.id,
            section_id=section.id,
            excerpt="A short summary of the whole book.",
        )
    )
    await db.commit()

    listed = (await client.get(f"/chats/{chat.id}/messages", headers=headers)).json()
    (citation,) = listed[-1]["citations"]

    assert citation["chunk_id"] is None
    assert citation["document_id"] == str(document.id)
    assert citation["document_name"] == "Dracula.txt"
    assert citation["excerpt"] == "A short summary of the whole book."
