from graph.chat_title import collapse_instant_title, generate_chat_title, parse_chat_title


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
