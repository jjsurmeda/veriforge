"""Reviewer tests (slice 6, TR-2/TR-3/TR-7).

Tier decision (documented per the slice brief): the scoring math —
`score_review`, `plan_delivery`, verdict→p mapping — is Critical-tier
because it is the eval gate's core signal (TRD §15); every branch is
covered. The LLM/Jev-touching paths (extraction parsing, verification,
the revision loop) follow the Standard LangGraph node-test rule: engine
and `complete_fn` are fakes, no live calls.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from graph.review import (
    ExtractedClaim,
    VerifiedClaim,
    _flagged,
    _needs_revision,
    _p_for_verdict,
    batch_claims,
    extract_claims,
    is_absence_claim,
    make_diff,
    parse_claims,
    plan_delivery,
    review_answer,
    revise_answer,
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
    async def test_citation_only_answer_is_unsupported_without_provider_calls(self) -> None:
        engine = _RecordingEngine()

        async def failing_complete(**kwargs: object) -> str:
            raise AssertionError("citation-only output must bypass claim extraction")

        result = await review_answer(
            engine=engine,
            run_id="r",
            answer="[1], [7], [2]",
            contexts=_ctx(),
            citation_count=3,
            small_model="small",
            litellm_model="generator",
            complete_fn=failing_complete,
        )

        assert [(claim.verdict, claim.p_supported) for claim in result.claims] == [
            ("unsupported", 0.0)
        ]
        assert result.scores is not None
        assert result.scores.faithfulness == 0.0
        assert engine.calls == []

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
            *,
            litellm_model: str,
            messages: list[dict[str, str]],
            metadata: dict[str, str],
            **kwargs: object,
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
            *,
            litellm_model: str,
            messages: list[dict[str, str]],
            metadata: dict[str, str],
            **kwargs: object,
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


class TestClaimExtractionTemperature:
    """KI-32: extraction runs at temperature 0. It is a parsing call whose
    claim list is the denominator of the faithfulness mean, so leaving it at
    the provider default made 4 of 20 fast20 items re-split their claims
    between runs (claim counts 2/5/4, 5/4/6, 1/1/3, 3/1/1)."""

    async def test_extraction_pins_temperature_zero(self) -> None:
        seen: list[dict[str, object]] = []

        async def fake_complete(**kwargs: object) -> str:
            seen.append(kwargs)
            return '[{"claim": "battery lasts ten hours", "citation_ids": [1]}]'

        claims = await extract_claims(
            answer="x [1]", small_model="small", complete_fn=fake_complete
        )

        assert seen[0]["temperature"] == 0
        # The intent assertion, not a "did not crash": the parsed output still
        # comes back, so the pin is on a live extraction call.
        assert [claim.text for claim in claims] == ["battery lasts ten hours"]

    async def test_the_revision_call_is_left_unpinned(self) -> None:
        """Only extraction was repinned. The revision pass rewrites prose, and
        answer variety there is a product choice, so it sends no temperature —
        `complete` treats None as "send nothing"."""
        seen: list[dict[str, object]] = []

        async def fake_complete(**kwargs: object) -> str:
            seen.append(kwargs)
            return "The battery lasts ten hours [1] (revised)."

        await revise_answer(
            answer="The battery lasts 100 years [1]",
            flagged=[
                VerifiedClaim(ExtractedClaim("c1", "x", [1], True), "contradicted", 0.0, "jev")
            ],
            contexts=[],
            litellm_model="big",
            complete_fn=fake_complete,
        )

        assert "temperature" not in seen[0]

    async def test_review_answer_pins_extraction(self) -> None:
        """End to end through `review_answer`, so the pin is asserted on the call
        the pipeline actually makes rather than on the helper in isolation."""
        seen: list[tuple[str, object]] = []

        async def fake_complete(**kwargs: Any) -> str:
            metadata: dict[str, str] = kwargs["metadata"]
            job = metadata.get("job", "")
            seen.append((job, kwargs.get("temperature", "<absent>")))
            if job == "claim_extraction":
                return '[{"claim": "the battery lasts 100 years", "citation_ids": [1]}]'
            return "The battery lasts ten hours [1] (revised)."

        await review_answer(
            engine=_RecordingEngine(),
            run_id="r",
            answer="The battery lasts 100 years [1]",
            contexts=_ctx(),
            citation_count=1,
            small_model="small",
            litellm_model="big",
            complete_fn=fake_complete,
        )

        extraction = [t for job, t in seen if job == "claim_extraction"]
        assert extraction and set(extraction) == {0}


class TestAbsenceClaimDetection:
    """KI-53: recognise the claim shape "the sources do not say X" so it is
    verified against the passages instead of passing through unscored."""

    def test_flagged_shapes(self) -> None:
        flagged = [
            "The sources do not provide any further details about the sisters' names.",
            "The sources do not specify which firmware version introduced this feature.",
            "The sources do not cover the character development in detail.",
            "No mention of 5 GHz Wi-Fi capability in any of the provided sources.",
            "There is no mention of a spare battery in the sources.",
            "The sources do not indicate any additional information about the AW-2000.",
        ]
        for text in flagged:
            assert is_absence_claim(ExtractedClaim("c", text, [], True)), text

    def test_normal_claims_are_not_flagged(self) -> None:
        normal = [
            "The AW-2000 battery lasts up to 10 hours on a full charge.",
            "The warranty does not cover damage from submersion.",
            "All models operate on 2.4 GHz with AES-256 encryption.",
            "There are five Bennet sisters as mentioned in the text.",
            "Firmware version 3.2.1 or later is required for the protocol.",
        ]
        for text in normal:
            assert not is_absence_claim(ExtractedClaim("c", text, [1], True)), text


class _CapturingEngine:
    """decide() that records every question verbatim and scripts verdicts
    per claim id (default `supported`)."""

    def __init__(self, verdicts: dict[str, str] | None = None) -> None:
        self.questions: dict[str, str] = {}
        self.call_count = 0
        self.verdicts = verdicts or {}

    async def decide(self, *, state, questions):  # type: ignore[no-untyped-def]
        self.call_count += 1
        self.questions.update({name: str(question.prompt) for name, question in questions.items()})
        return {
            name: Answer(
                engine="jev",
                latency_ms=1,
                value=self.verdicts.get(name, "supported"),
                probability=0.9,
                probabilities={"supported": 0.9},
            )
            for name in questions
        }


def _two_ctx() -> list[ExpandedContext]:
    from uuid import uuid4

    chunks = [
        ScoredChunk(
            chunk_id=uuid4(),
            document_id=None,
            document_name=None,
            section_id=None,
            ord=0,
            page=None,
            text="The AW-2000 battery lasts ten hours on a full charge.",
            heading_path=None,
            source_type="document",
            vector_score=0.5,
            bm25_score=0.5,
            fused_score=0.5,
        ),
        ScoredChunk(
            chunk_id=uuid4(),
            document_id=None,
            document_name=None,
            section_id=None,
            ord=0,
            page=None,
            text="The device ships with a spare battery and a USB-C cable.",
            heading_path=None,
            source_type="document",
            vector_score=0.5,
            bm25_score=0.5,
            fused_score=0.5,
        ),
    ]
    return [ExpandedContext(chunk, chunk.text) for chunk in chunks]


class TestAbsenceVerification:
    async def test_absence_claim_rides_the_same_batch_and_sees_all_passages(self) -> None:
        engine = _CapturingEngine()
        claims = [
            ExtractedClaim("c1", "The battery lasts ten hours.", [1], True),
            # Uncited, like every recorded false absence in the P1b sheet.
            ExtractedClaim(
                "c2",
                "The sources do not state that the device ships with a spare battery.",
                [],
                True,
            ),
        ]
        _verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_two_ctx(), citation_count=1
        )
        assert engine.call_count == 1
        assert "Verify one claim against its cited sources" in engine.questions["c1"]
        assert "Verify one absence claim" in engine.questions["c2"]
        # The false absence lives in the SECOND passage, not the cited one:
        # the question must carry every passage to be checkable at all.
        assert "spare battery" in engine.questions["c2"]
        assert "lasts ten hours" in engine.questions["c2"]

    async def test_false_absence_is_contradicted_and_lowers_faithfulness(self) -> None:
        engine = _CapturingEngine(verdicts={"c2": "contradicted"})
        claims = [
            ExtractedClaim("c1", "The battery lasts ten hours.", [1], True),
            ExtractedClaim(
                "c2",
                "The sources do not state that the device ships with a spare battery.",
                [],
                True,
            ),
        ]
        verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_two_ctx(), citation_count=1
        )
        by_id = {v.claim.claim_id: v for v in verified}
        assert by_id["c2"].verdict == "contradicted"
        assert by_id["c2"].p_supported == 0.0
        scores = score_review(verified, citation_count=1)
        assert scores.faithfulness == pytest.approx(0.5)
        assert scores.min_support == 0.0
        assert _needs_revision(verified) is True

    async def test_true_absence_is_supported(self) -> None:
        engine = _CapturingEngine()
        claims = [
            ExtractedClaim("c1", "The battery lasts ten hours.", [1], True),
            ExtractedClaim(
                "c2", "The sources do not mention a leather carrying case.", [], True
            ),
        ]
        verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_two_ctx(), citation_count=1
        )
        by_id = {v.claim.claim_id: v for v in verified}
        assert by_id["c2"].verdict == "supported"
        scores = score_review(verified, citation_count=1)
        assert scores.faithfulness == pytest.approx(1.0)

    async def test_answer_without_absence_claim_makes_no_extra_call(self) -> None:
        """The KI-53 routing must be invisible to clean answers: same number
        of decide calls and the same standard question text as before the
        fix (one batched question per cited factual claim)."""
        engine = _CapturingEngine()
        claims = [
            ExtractedClaim("c1", "The battery lasts ten hours.", [1], True),
            ExtractedClaim("c2", "It ships with a USB-C cable.", [2], True),
        ]
        verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_two_ctx(), citation_count=2
        )
        assert engine.call_count == 1
        assert set(engine.questions) == {"c1", "c2"}
        for prompt in engine.questions.values():
            assert "absence" not in prompt
            assert prompt.count("[Sources]") == 0
        assert [v.verdict for v in verified] == ["supported", "supported"]

    async def test_uncited_normal_claim_still_scores_unsupported_without_a_call(self) -> None:
        engine = _CapturingEngine()
        claims = [ExtractedClaim("c1", "an uncited fact", [], True)]
        verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=_two_ctx(), citation_count=0
        )
        assert engine.call_count == 0
        assert verified[0].verdict == "unsupported"

    async def test_absence_questions_batch_by_their_own_token_weight(self, monkeypatch):
        """An absence question carries every passage, so its token count —
        not the standard claim question's — must drive the batch split."""
        from graph import review as review_module

        engine = _CapturingEngine()
        monkeypatch.setattr(review_module, "BATCH_TOKEN_BUDGET", 60)
        long_passage = "word " * 400
        from uuid import uuid4

        big = ScoredChunk(
            chunk_id=uuid4(),
            document_id=None,
            document_name=None,
            section_id=None,
            ord=0,
            page=None,
            text=long_passage,
            heading_path=None,
            source_type="document",
            vector_score=0.5,
            bm25_score=0.5,
            fused_score=0.5,
        )
        contexts = [
            ExpandedContext(big, big.text),
            *_two_ctx(),
        ]
        claims = [
            ExtractedClaim("c1", "The sources do not state anything about the battery.", [], True),
            ExtractedClaim("c2", "The sources do not mention a warranty.", [], True),
        ]
        verified, _ = await verify_claims(
            engine, run_id="r", claims=claims, contexts=contexts, citation_count=0
        )
        # Each absence question exceeds the 60-token budget on its own, so
        # they cannot share a batch: two calls, one question each.
        assert engine.call_count == 2
        assert [v.claim.claim_id for v in verified] == ["c1", "c2"]


class TestGroundedAnswerV4Captures:
    """KI-53, mechanism proof (live capture 2026-10-04, gpt-4o-mini, the
    exact P1b passages): grounded_answer.md v3 still emits the false
    absence on at least one flagged row, v4 does not emit an unconditional
    absence sentence on any single-part row, and the 5 GHz rows may only
    name the 5 GHz part as the uncovered part — never conclude the product
    lacks 5 GHz. Captured in scripts/p2a_item1_mechanism.py; the test reads
    the checked-in fixture, it never calls a live model."""

    _CAPTURES = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "p2a_item1_captures.json").read_text()
    )

    def _sentences(self, text: str) -> list[str]:
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    def test_v3_capture_still_shows_the_defect(self) -> None:
        # Row 13: the recorded false absence — the names ARE in the
        # passages, the v3 answer claims they are not.
        v3 = self._CAPTURES["acceptance:fact-bennet-sisters"]["v3_answer"]
        assert any(is_absence_claim(ExtractedClaim("c", s, [], True)) for s in self._sentences(v3))

    def test_v4_single_part_rows_have_no_absence_sentence(self) -> None:
        single_part = [
            "acceptance:fact-bennet-sisters",
            "export:20261002-061544:10",
            "export:20261002-061544:11",
            "export:20261002-061544:14",
            "export:20261002-061544:19",
            "export:20261002-061544:5",
        ]
        for answer_id in single_part:
            v4 = self._CAPTURES[answer_id]["v4_answer"]
            offending = [
                s
                for s in self._sentences(v4)
                if is_absence_claim(ExtractedClaim("c", s, [], True))
            ]
            assert not offending, f"{answer_id}: v4 answer still carries {offending!r}"

    def test_v4_five_ghz_rows_only_name_the_five_ghz_part(self) -> None:
        for answer_id in (
            "export:20261002-061544:8",
            "export:20261002-062146:12",
        ):
            v4 = self._CAPTURES[answer_id]["v4_answer"]
            for sentence in self._sentences(v4):
                if is_absence_claim(ExtractedClaim("c", sentence, [], True)):
                    assert "5 GHz" in sentence, f"{answer_id}: {sentence!r}"
            # The recorded defect: a conclusion the sources do not state.
            assert "does not support" not in v4.lower(), v4
            assert "cannot run" not in v4.lower(), v4
