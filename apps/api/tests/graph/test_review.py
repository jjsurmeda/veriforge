"""Reviewer tests (slice 6, TR-2/TR-3/TR-7).

Tier decision (documented per the slice brief): the scoring math —
`score_review`, `plan_delivery`, verdict→p mapping — is Critical-tier
because it is the eval gate's core signal (TRD §15); every branch is
covered. The LLM/Jev-touching paths (extraction parsing, verification,
the revision loop) follow the Standard LangGraph node-test rule: engine
and `complete_fn` are fakes, no live calls.
"""

import pytest

from graph.review import (
    ExtractedClaim,
    VerifiedClaim,
    _flagged,
    _needs_revision,
    _p_for_verdict,
    batch_claims,
    make_diff,
    parse_claims,
    plan_delivery,
    review_answer,
    score_review,
    verify_claims,
)
from retrieval.expand import ExpandedContext
from retrieval.hybrid import ScoredChunk
from schemas.decisions import Answer


def _vc(
    text: str,
    verdict: str,
    p: float,
    *,
    factual: bool = True,
    citation_ids: list[int] | None = None,
) -> VerifiedClaim:
    return VerifiedClaim(
        ExtractedClaim("c", text, citation_ids or [], factual),
        verdict,
        p,
        "jev",
    )


class TestScoringMath:
    def test_faithfulness_formula(self) -> None:
        claims = [
            _vc("a", "supported", 1.0),
            _vc("b", "supported", 0.9),
            _vc("c", "partial", 0.5),
            _vc("d", "unsupported", 0.0),
        ]
        scores = score_review(claims, citation_count=4)
        assert scores.faithfulness == pytest.approx((2 + 0.5) / 4)
        assert scores.min_support == 0.0

    def test_non_factual_claims_excluded(self) -> None:
        claims = [
            _vc("fact", "supported", 1.0),
            _vc("greeting", "skipped", 0.0, factual=False),
        ]
        scores = score_review(claims, citation_count=1)
        assert scores.faithfulness == 1.0
        assert scores.min_support == 1.0

    def test_zero_factual_claims_is_perfect(self) -> None:
        scores = score_review([], citation_count=0)
        assert (scores.faithfulness, scores.min_support, scores.citation_precision) == (
            1.0,
            1.0,
            1.0,
        )

    def test_citation_precision_counts_supported_pairs(self) -> None:
        claims = [
            _vc("a", "supported", 1.0, citation_ids=[1, 2]),
            _vc("b", "partial", 0.5, citation_ids=[2]),
            _vc("c", "contradicted", 0.0, citation_ids=[3]),
        ]
        scores = score_review(claims, citation_count=3)
        assert scores.citation_precision == pytest.approx(2 / 4)

    def test_citation_precision_zero_when_factual_claims_uncited(self) -> None:
        claims = [_vc("a", "unsupported", 0.0)]
        scores = score_review(claims, citation_count=2)
        assert scores.citation_precision == 0.0

    def test_min_support_is_lowest_across_factual(self) -> None:
        claims = [
            _vc("a", "supported", 0.8),
            _vc("b", "partial", 0.5),
            _vc("c", "supported", 0.6),
            _vc("skip", "skipped", 0.0, factual=False),
        ]
        assert score_review(claims, 3).min_support == pytest.approx(0.5)

    def test_p_for_verdict(self) -> None:
        answer = Answer(
            engine="jev",
            latency_ms=1,
            value="supported",
            probability=0.7,
            probabilities={"supported": 0.9, "partial": 0.1},
        )
        assert _p_for_verdict("supported", answer) == pytest.approx(0.9)
        assert _p_for_verdict("partial", answer) == 0.5
        assert _p_for_verdict("unsupported", answer) == 0.0
        no_probs = Answer(engine="fallback", latency_ms=1, value="supported", probability=0.8)
        assert _p_for_verdict("supported", no_probs) == pytest.approx(0.8)


class TestPlanDelivery:
    def test_deep_always_holds(self) -> None:
        assert (
            plan_delivery(mode="deep", risk="low", sufficiency_p=0.99, sufficient_threshold=0.6)
            == "hold"
        )

    def test_fast_always_streams(self) -> None:
        assert (
            plan_delivery(mode="fast", risk="high", sufficiency_p=0.1, sufficient_threshold=0.6)
            == "stream"
        )

    def test_auto_high_risk_holds(self) -> None:
        assert (
            plan_delivery(mode="auto", risk="high", sufficiency_p=0.95, sufficient_threshold=0.6)
            == "hold"
        )

    def test_auto_sufficiency_within_0_1_of_threshold_holds(self) -> None:
        assert (
            plan_delivery(mode="auto", risk="low", sufficiency_p=0.68, sufficient_threshold=0.6)
            == "hold"
        )

    def test_auto_low_risk_confident_streams(self) -> None:
        assert (
            plan_delivery(mode="auto", risk="low", sufficiency_p=0.9, sufficient_threshold=0.6)
            == "stream"
        )


class TestParseClaims:
    def test_parses_fence_and_fields(self) -> None:
        response = (
            '```json\n[{"claim": "Battery lasts 10h", "citation_ids": [1], '
            '"is_factual": true}, {"claim": "Hope this helps", '
            '"citation_ids": [], "is_factual": false}]\n```'
        )
        claims = parse_claims(response)
        assert len(claims) == 2
        assert claims[0].claim_id == "c1"
        assert claims[0].citation_ids == [1]
        assert claims[1].is_factual is False

    def test_rejects_garbage(self) -> None:
        assert parse_claims("not json") == []
        assert parse_claims('{"claim": "single object"}') == []
        assert parse_claims('[{"no_claim": true}]') == []


class _RecordingEngine:
    """decide() that answers every question `supported` and records calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, int]] = []

    async def decide(self, *, state, questions):  # type: ignore[no-untyped-def]
        self.calls.append({name: len(q.prompt) for name, q in questions.items()})
        return {
            name: Answer(
                engine="jev",
                latency_ms=1,
                value="supported",
                probability=0.9,
                probabilities={"supported": 0.9},
            )
            for name in questions
        }


def _ctx() -> list[ExpandedContext]:
    from uuid import uuid4

    chunk = ScoredChunk(
        chunk_id=uuid4(),
        document_id=None,
        document_name="doc.pdf",
        section_id=None,
        ord=0,
        page=1,
        text="The AW-2000 battery lasts ten hours.",
        heading_path=None,
        source_type="document",
        vector_score=0.5,
        bm25_score=0.5,
        fused_score=0.5,
        rerank_score=0.9,
    )
    return [ExpandedContext(chunk, chunk.text)]


class TestVerifyClaims:
    async def test_uncited_claim_scores_unsupported_without_jev_call(self) -> None:
        engine = _RecordingEngine()
        claims = [
            ExtractedClaim("c1", "uncited fact", [], True),
            ExtractedClaim("c2", "greeting", [], False),
        ]
        verified, answers = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_ctx(), citation_count=1
        )
        assert engine.calls == []
        assert answers == []
        by_id = {v.claim.claim_id: v for v in verified}
        assert by_id["c1"].verdict == "unsupported"
        assert by_id["c1"].p_supported == 0.0
        assert by_id["c1"].engine == "n/a"
        assert by_id["c2"].verdict == "skipped"

    async def test_cited_claims_verified_and_ordered(self) -> None:
        engine = _RecordingEngine()
        claims = [
            ExtractedClaim("c1", "fact one", [1], True),
            ExtractedClaim("c2", "greeting", [], False),
            ExtractedClaim("c3", "fact two", [1], True),
        ]
        verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_ctx(), citation_count=1
        )
        assert len(engine.calls) == 1
        assert [v.claim.claim_id for v in verified] == ["c1", "c2", "c3"]
        assert verified[0].verdict == "supported"
        assert verified[0].p_supported == pytest.approx(0.9)

    def test_batching_splits_on_token_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from graph import review as review_module

        monkeypatch.setattr(review_module, "BATCH_TOKEN_BUDGET", 10)
        claims = [
            ExtractedClaim(f"c{i}", f"claim number {i} with text", [1], True) for i in range(5)
        ]
        batches = batch_claims(claims, _ctx())
        assert len(batches) >= 2
        assert sum(len(b) for b in batches) == 5


class TestRevisionLoop:
    async def test_contradicted_claim_triggers_exactly_one_revision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake_complete(
            *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
        ) -> str:
            job = metadata.get("job", "")
            calls.append(job)
            if job == "claim_extraction":
                answer = messages[1]["content"] if len(messages) > 1 else ""
                if "revised" in answer:
                    return (
                        '[{"claim": "revised supported fact", '
                        '"citation_ids": [1], "is_factual": true}]'
                    )
                return (
                    '[{"claim": "the battery lasts 100 years", '
                    '"citation_ids": [1], "is_factual": true}]'
                )
            if job == "revision":
                return "The battery lasts ten hours [1] (revised)."
            raise AssertionError(f"unexpected job {job}")

        engine = _RecordingEngine()
        # First verification round contradicts; the post-revision round supports.
        rounds = {"n": 0}

        original_decide = engine.decide

        async def scripted_decide(*, state, questions):  # type: ignore[no-untyped-def]
            rounds["n"] += 1
            verdict = "contradicted" if rounds["n"] == 1 else "supported"
            return {
                name: Answer(
                    engine="jev",
                    latency_ms=1,
                    value=verdict,
                    probability=0.9 if verdict == "supported" else 0.1,
                    probabilities={verdict: 0.9 if verdict == "supported" else 0.1},
                )
                for name in questions
            }

        monkeypatch.setattr(engine, "decide", scripted_decide)
        assert original_decide is not None

        result = await review_answer(
            engine=engine,
            run_id="r",
            answer="The battery lasts 100 years [1]",
            contexts=_ctx(),
            citation_count=1,
            small_model="small",
            litellm_model="big",
            complete_fn=fake_complete,
        )
        # Exactly one revision pass: one revision call, not a loop.
        assert calls.count("revision") == 1
        assert result.revised_text is not None
        assert "revised" in result.revised_text
        assert result.diff is not None and "-The battery lasts 100 years [1]" in result.diff
        assert result.scores is not None
        assert result.scores.faithfulness == pytest.approx(1.0)

    async def test_no_revision_when_all_supported(self) -> None:
        calls: list[str] = []

        async def fake_complete(
            *, litellm_model: str, messages: list[dict[str, str]], metadata: dict[str, str]
        ) -> str:
            calls.append(metadata.get("job", ""))
            return '[{"claim": "battery lasts ten hours", "citation_ids": [1], "is_factual": true}]'

        result = await review_answer(
            engine=_RecordingEngine(),
            run_id="r",
            answer="The battery lasts ten hours [1]",
            contexts=_ctx(),
            citation_count=1,
            small_model="small",
            litellm_model="big",
            complete_fn=fake_complete,
        )
        assert "revision" not in calls
        assert result.revised_text is None


class TestNeedsRevision:
    def test_low_min_support_flags(self) -> None:
        claims = [_vc("a", "supported", 1.0), _vc("b", "partial", 0.4)]
        assert _needs_revision(claims) is True
        assert _flagged(claims)[0].claim.text == "b"

    def test_contradicted_flags_even_with_high_support(self) -> None:
        claims = [_vc("a", "supported", 1.0), _vc("b", "contradicted", 0.0)]
        assert _needs_revision(claims) is True

    def test_healthy_answer_passes(self) -> None:
        claims = [_vc("a", "supported", 0.9), _vc("b", "partial", 0.5)]
        assert _needs_revision(claims) is False


def test_make_diff() -> None:
    diff = make_diff("line one\nline two", "line one\nline three")
    assert "-line two" in diff and "+line three" in diff
