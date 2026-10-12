# RAG reference checklist

Every design review and every quality brief checks the pipeline against this
list, not only against open known issues. Added 2026-10-13 after reviews
missed a plain-relevance rerank prompt and a one-size generator prompt.

| Stage | Proven practice | Veriforge (2026-10-13) |
| --- | --- | --- |
| Chunking | Small chunks for search, larger parent for context (small-to-big), overlap | ✅ 300-token children, 45 overlap, 2000-token sections |
| Retrieval | Hybrid BM25 + vector, fused (RRF), wide candidate pool | ✅ 50 + 50, fused 40 |
| Query | Rewrite and variants; validate the rewrite is a query | ⚠️ rewrite not validated (KI-73) |
| Rerank | Ask whether the passage **answers** the question, graded (off-topic / related / partly / fully), batched | ❌ plain "how relevant" 0–1 (phase 1e) |
| Context order | Best passages at the start **and** end (lost in the middle) | ❌ rank order only |
| Whole-document questions | Document or section summaries retrieved for gist questions (RAPTOR / summary index) | ❌ none; gist questions see only the passages that match |
| Generator prompt | Sources first, question last, numbered citations; read all sources; combine stated facts; resolve conflicts (later explanation wins); per-intent instructions | ⚠️ layout ✅, rules guardrail-only, static (phase 1e) |
| Abstention | One clear sufficiency signal; few independent vetoes | ⚠️ several model-judged vetoes in series (sufficiency, relevance, entity) |
| Verification | Post-hoc claim check against cited passages | ✅ reviewer |
| Evaluation | Answer correctness and context recall on a labelled set, not only safety | ⚠️ content check added phase 1e; context recall deferred |
