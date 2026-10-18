"""Jev's gate values are calibrated numbers (ADR-006); R2c must not move them."""

import pytest

from decisions.thresholds import RerankerUncalibrated, reranker_threshold


@pytest.mark.parametrize("reranker", ["jev", "fallback"])
def test_jev_gate_values_are_unchanged(reranker: str) -> None:
    assert reranker_threshold("evidence_floor", reranker) == 0.455
    assert reranker_threshold("stream_line", reranker) == 0.60


@pytest.mark.parametrize("reranker", ["cohere", "nvidia", "fused"])
def test_uncalibrated_rerankers_are_refused(reranker: str) -> None:
    with pytest.raises(RerankerUncalibrated):
        reranker_threshold("evidence_floor", reranker)
