"""Pure parts of the reranker comparison harness (R2c item 6)."""

import pytest

from scripts.compare_rerankers import ndcg_at_k, paired, percentile, render_md


def test_ndcg_is_one_for_a_perfect_order_and_lower_when_the_hit_is_late() -> None:
    assert ndcg_at_k(["a", "x"], {"a"}) == pytest.approx(1.0)
    assert 0 < ndcg_at_k(["x", "y", "a"], {"a"}) < 1
    assert ndcg_at_k(["x"], {"a"}) == 0.0
    assert ndcg_at_k(["x"], set()) == 0.0


def test_paired_labels_differences_under_two_items_as_ties() -> None:
    hits = {
        "jev": {"a": True, "b": True, "c": False},
        "cohere": {"a": True, "b": False, "c": True},
    }
    p = paired(hits, "jev", "cohere")
    assert (p["wins"], p["losses"], p["verdict"]) == (["c"], ["b"], "tie")
    hits["cohere"] = {"a": False, "b": False, "c": False}
    assert paired(hits, "jev", "cohere")["verdict"] == "worse"


def test_percentile_and_render_name_the_skipped_and_the_no_key_run() -> None:
    assert percentile([10, 20, 30, 40], 0.5) == 20
    result = {
        "summary": {
            "jev": {
                "hits": 1,
                "items": 2,
                "recall_at_8": 0.5,
                "ndcg_at_10": 0.4,
                "latency_p50_ms": 1,
                "latency_p95_ms": 2,
                "cost_per_1k_queries_usd": None,
                "cost_source": "not measured",
            },
        },
        "vs_jev": {},
    }
    from pathlib import Path

    md = render_md(result, skipped={"cohere": "no API key"}, export=Path("x.json"))
    assert "Skipped: `cohere` (no API key)" in md
    assert "no Cohere or NVIDIA key" in md
