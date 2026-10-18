"""Section and document summaries: the retrieval SQL and the ownership filter
(R2a-2 item 4, TRD §9.1 step 6).

**Written before the code, on purpose, and against a real database**
(testing.md: `retrieval` is Critical-tier and "the ownership-filter SQL is the
thing under test"). A summary index is a *second* copy of a corpus, reachable
by a second query. A first query into a table nobody has ever queried is
exactly where a missing ownership predicate costs a data leak rather than a
wrong answer, and the only thing that catches it is a test written before the
predicate exists.

The three things pinned here:

1. **A summary row obeys the same server-side scope as a chunk.** A user who
   cannot retrieve a document's chunks cannot retrieve its summary, even by
   naming the summary's section, and even when the document is not in their
   collection but is `shared` and owned by someone else.
2. **Client filters only narrow.** A crafted `document_ids` filter cannot widen
   a summary search the way it cannot widen a chunk search — the summary query
   joins through `documents` and `collections` under the *same* injected
   predicate, rather than a simplified one.
3. **Summaries are only retrieved for a gist question and for the corrective
   retrieval.** `summarize` intent, or the corrective pass. A `lookup` never
   sees them, because a summary is not a passage and citing one as evidence
   would put a model's own words in the answer's citation trail.

Every test is against the test Postgres; none of them calls a model. The
summariser itself is covered separately with a fake `complete`.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from retrieval.filters import ClientFilters, Ownership
from retrieval.summaries import (
    SUMMARY_KINDS,
    search_summaries,
    summaries_allowed_for,
)
from tests.retrieval.conftest import (
    add_chunk,
    make_chat,
    make_collection,
    make_document,
    make_section,
    make_user,
    vec,
)


async def _corpus(db: AsyncSession, email: str) -> dict[str, Any]:
    """One document, one section, one chunk, one section summary, one document
    summary — the shape `ingest` will write."""
    user = await make_user(db, email)
    private = await make_collection(db, user, f"{email}-private")
    document = await make_document(db, private, "study-in-scarlet.txt")
    section = await make_section(db, document, ord=1)
    await add_chunk(
        db,
        document=document,
        section=section,
        ord=0,
        text_="Watson served in Afghanistan before he met Holmes.",
        embedding=vec(1),
    )
    return {
        "user": user,
        "collection": private,
        "document": document,
        "section": section,
        "db": db,
    }


@pytest.fixture
async def alice(db: AsyncSession) -> dict[str, Any]:
    return await _corpus(db, "summaries-alice@test.dev")


@pytest.fixture
async def bob(db: AsyncSession) -> dict[str, Any]:
    return await _corpus(db, "summaries-bob@test.dev")


async def _seed_summaries(corpus: dict[str, Any]) -> dict[str, Any]:
    """Write the two summary rows TRD §9.1 step 6 asks for."""
    from db.models import Summary

    db: AsyncSession = corpus["db"]
    section = corpus["section"]
    rows = {
        "section": Summary(
            document_id=corpus["document"].id,
            section_id=section.id,
            kind="section",
            ord=1,
            heading_path="Chapter 1",
            text="A war surgeon meets Holmes and shares a flat with him.",
            embedding=vec(2, bump=5.0),
        ),
        "document": Summary(
            document_id=corpus["document"].id,
            section_id=None,
            kind="document",
            ord=0,
            heading_path="The whole book",
            text="A detective and his doctor friend solve crimes in London.",
            embedding=vec(3, bump=5.0),
        ),
    }
    db.add_all(rows.values())
    await db.commit()
    return rows


def _ownership(corpus: dict[str, Any], **kwargs: Any) -> Ownership:
    return Ownership(
        user_id=corpus["user"].id,
        collection_ids=[corpus["collection"].id],
        **kwargs,
    )


# --- the shape of a summary row ------------------------------------------------


async def test_a_summary_row_has_a_kind_and_hangs_off_its_section(
    alice: dict[str, Any],
) -> None:
    """Two kinds in one table, discriminated by `kind` and by whether
    `section_id` is set: a document summary is built from its section
    summaries and has no section of its own. A single nullable column with no
    discriminator would make "a section summary with no section" a reachable
    state."""
    from db.models import Summary

    rows = await _seed_summaries(alice)

    assert set(SUMMARY_KINDS) == {"section", "document"}
    assert rows["section"].kind == "section" and rows["section"].section_id is not None
    assert rows["document"].kind == "document" and rows["document"].section_id is None
    assert all(isinstance(r, Summary) for r in rows.values())


async def test_deleting_a_document_deletes_its_summaries(alice: dict[str, Any]) -> None:
    """The FK is `ON DELETE CASCADE`, the same as chunks and sections. A summary
    left behind after its document is deleted is a row that retrieval can still
    reach, and it would be a summary of a document the user can no longer see."""
    from sqlalchemy import delete, func, select

    from db.models import Summary

    await _seed_summaries(alice)
    db: AsyncSession = alice["db"]

    await db.execute(delete(Summary).where(Summary.document_id == alice["document"].id))
    await db.commit()

    count = select(func.count()).select_from(Summary).where(
        Summary.document_id == alice["document"].id
    )
    remaining = (await db.execute(count)).scalar_one()
    assert remaining == 0


# --- the ownership filter (the reason these tests exist) -----------------------


async def test_a_summary_is_retrieved_by_its_owner(alice: dict[str, Any]) -> None:
    await _seed_summaries(alice)

    found = await search_summaries(
        alice["db"],
        query_text="a detective and his doctor friend",
        query_embedding=vec(3, bump=5.0),
        ownership=_ownership(alice),
    )

    assert {row.kind for row in found} == {"section", "document"}
    assert all(row.document_id == alice["document"].id for row in found)


async def test_another_users_summary_is_never_retrieved(
    alice: dict[str, Any], bob: dict[str, Any]
) -> None:
    """The one that matters. Two users, near-identical corpora, summaries in
    both. Bob's query must not return a single one of Alice's rows — not through
    the vector arm, not through the BM25 arm, not through the fusion.

    The text is deliberately *the same* in both documents: a filter that matched
    on content would find Alice's row, so this fails unless the ownership
    predicate is inside every arm of the query."""
    await _seed_summaries(alice)
    await _seed_summaries(bob)

    found = await search_summaries(
        bob["db"],
        query_text="A detective and his doctor friend solve crimes in London.",
        query_embedding=vec(3, bump=5.0),
        ownership=_ownership(bob),
    )

    assert found, "Bob's own summary must be findable, or this test proves nothing"
    assert all(row.document_id == bob["document"].id for row in found), (
        "another user's summary rows reached Bob's results"
    )


async def test_a_shared_document_summary_is_visible_to_everyone(
    alice: dict[str, Any], bob: dict[str, Any]
) -> None:
    """`shared` is the same rule chunks obey (ADR-002): ownership OR visibility.
    A summary index that only honoured ownership would make a shared library's
    gist questions unanswerable, and one that only honoured the collection list
    would leak.

    The scope is built the way `chats.scope.resolve_scope` builds it — Bob's own
    collection **plus** every shared one — because that is what a chat actually
    gets. Handing an empty `collection_ids` instead would assert something the
    product never does: `build_scope` requires both clauses, so an empty list
    matches nothing at all, which is the opposite of what this test is about."""
    from chats.scope import resolve_scope

    await _seed_summaries(alice)
    await bob["db"].execute(_share_collection(alice["collection"]))
    await bob["db"].commit()

    bob_chat = await make_chat(bob["db"], bob["user"])
    scope = await resolve_scope(bob["db"], bob_chat, [])
    assert alice["collection"].id in scope, "a shared collection is in everyone's scope"

    found = await search_summaries(
        bob["db"],
        query_text="A detective and his doctor friend solve crimes in London.",
        query_embedding=vec(3, bump=5.0),
        ownership=Ownership(user_id=bob["user"].id, collection_ids=list(scope)),
    )

    assert any(row.document_id == alice["document"].id for row in found), (
        "a shared library's summaries must be retrievable by another user"
    )


def _share_collection(collection: Any) -> Any:
    from sqlalchemy import update

    from db.models import Collection

    return update(Collection).where(Collection.id == collection.id).values(visibility="shared")


async def test_a_client_filter_can_only_narrow_a_summary_search(
    alice: dict[str, Any], bob: dict[str, Any]
) -> None:
    """The adversarial case from testing.md: a client sends a crafted
    `document_ids` filter naming someone else's document. On chunks the
    ownership predicate still holds and the filter is merely ANDed inside it.
    A summary query written with a simplified predicate would return the row.

    So: Bob asks for Alice's document by id and gets nothing."""
    await _seed_summaries(alice)
    await _seed_summaries(bob)

    found = await search_summaries(
        bob["db"],
        query_text="A detective and his doctor friend solve crimes in London.",
        query_embedding=vec(3, bump=5.0),
        ownership=_ownership(bob),
        filters=ClientFilters(document_ids=[alice["document"].id]),
    )

    assert all(row.document_id != alice["document"].id for row in found), (
        "a client-supplied document_ids filter widened the summary search past "
        "the ownership scope"
    )


async def test_a_client_filter_that_names_only_owned_documents_still_narrows(
    alice: dict[str, Any],
) -> None:
    """The other half, or the filter is untested: naming a document Bob owns
    that is not in his scope must narrow to nothing rather than being ignored."""
    await _seed_summaries(alice)
    other = await make_collection(alice["db"], alice["user"], "not-in-scope")
    other_doc = await make_document(alice["db"], other, "other.txt")

    found = await search_summaries(
        alice["db"],
        query_text="A detective and his doctor friend solve crimes in London.",
        query_embedding=vec(3, bump=5.0),
        ownership=_ownership(alice),
        filters=ClientFilters(document_ids=[other_doc.id]),
    )

    assert found == [], "the filter was ignored rather than applied"


# --- when summaries may be retrieved at all -----------------------------------


def test_summaries_are_retrieved_for_a_gist_question() -> None:
    assert summaries_allowed_for("summarize") is True


def test_the_corrective_retrieval_may_use_summaries_for_any_intent() -> None:
    """The one place the rule loosens, deliberately. The corrective pass is the
    last chance a run gets after the gate failed, it is already the case where
    the evidence was too thin, and a summary is ordinary in-scope evidence
    retrieved under ordinary ownership rules. A failed `lookup` that finds the
    answer in a document summary has answered a question the corpus could
    answer; the alternative is an abstention claiming it could not."""
    assert summaries_allowed_for("lookup", corrective=True) is True
    assert summaries_allowed_for("summarize", corrective=True) is True


def test_a_lookup_never_retrieves_summaries_on_the_first_retrieval() -> None:
    """A summary is the model's own words about a section, not the section. A
    first-pass `lookup` that cited one would put a paraphrase in the citation
    trail and let the generator quote a summary as if the source said it."""
    assert summaries_allowed_for("lookup") is False


def test_an_unknown_intent_is_treated_as_a_lookup_not_as_a_gist_question() -> None:
    """The safe direction. A new intent added to ingress but not here would
    otherwise default to *allowing* summaries, which is the direction that
    puts paraphrases in citations."""
    assert summaries_allowed_for("something-new") is False
    assert summaries_allowed_for("chitchat") is False
    assert summaries_allowed_for("library") is False
    # ...and the loosening is scoped to the corrective pass, not to the
    # unknown intent: it is the occasion that loosens, not the question.
    assert summaries_allowed_for("something-new", corrective=True) is True


# --- the results carry what a citation would need ------------------------------


async def test_a_retrieved_summary_carries_its_section_and_document(
    alice: dict[str, Any],
) -> None:
    """A summary that cannot be cited is a summary the generator has to repeat
    from memory, which is the failure the whole index exists to avoid. The row
    has to name the document and, for a section summary, the section."""
    rows = await _seed_summaries(alice)

    found = await search_summaries(
        alice["db"],
        query_text="A detective and his doctor friend solve crimes in London.",
        query_embedding=vec(3, bump=5.0),
        ownership=_ownership(alice),
    )

    by_kind = {row.kind: row for row in found}
    assert by_kind["section"].section_id == rows["section"].section_id == alice["section"].id
    assert by_kind["section"].document_id == alice["document"].id
    assert by_kind["section"].document_name == "study-in-scarlet.txt"
    assert by_kind["document"].section_id is None
    assert by_kind["document"].document_name == "study-in-scarlet.txt"
    assert by_kind["document"].heading_path == "The whole book"


async def test_a_summary_that_matches_no_passage_still_ranks(alice: dict[str, Any]) -> None:
    """The whole point of the index: a gist question matches no single 300-token
    child. `broad-alice` scored 0.36 on the passages that DID contain the arc
    (KI-70), and that is the number this table exists to beat.

    So the query here shares nothing with the summary text — "the overall arc
    of the story" appears in no summary — and the vector arm has to carry the
    match on its own."""
    await _seed_summaries(alice)

    found = await search_summaries(
        alice["db"],
        query_text="Summarise the overall arc of the story and its main figures.",
        query_embedding=vec(9, bump=5.0),
        ownership=_ownership(alice),
    )

    assert found, "a gist question must reach the summaries"


async def test_no_summaries_in_scope_returns_an_empty_list_not_none(
    bob: dict[str, Any],
) -> None:
    """Bob has no summaries written yet. The retrieval path has to handle that
    as an ordinary empty result, because the backfill is resumable and the run
    that reaches step 6 before the backfill has covered its document is normal,
    not an error."""
    assert (
        await search_summaries(
            bob["db"],
            query_text="anything",
            query_embedding=vec(4),
            ownership=_ownership(bob),
        )
        == []
    )
