# RAG reference checklist

Every design review and every quality brief checks the pipeline against this
list, not only against open known issues.

**A row is ✅ only with a measurement:** the number, the set it was measured
on, and the date. A component that exists but is unmeasured is ⚠️, however
complete it looks. (2026-10-18: the Retrieval row was ✅ for structure while
the fusion weight read ~0 and BM25 contributed nothing; four calibration
rounds were built on it.)

| Stage | Proven practice | Veriforge (2026-10-13) |
| --- | --- | --- |
| Chunking | Small chunks for search, larger parent for context (small-to-big), overlap | ✅ 300-token children, 45 overlap, 2000-token sections |
| Retrieval | Hybrid BM25 + vector, fused (RRF), wide candidate pool | ✅ 50 + 50, fused 40 + 8 BM25-only reserve: answer passage in the pool for 23/23 answerable books items, every gist item's document 10/10 (`scripts/measure_recall.py`, R2a-4 proof's queries, 2026-10-18). The ingress `lexical_weight` reads 0.00–0.04, so the reserve is what keeps BM25 in |
| Query | Rewrite and variants; validate the rewrite is a query | ✅ `is_query_shape` gates the rewrite and every variant line; a `chitchat` turn that names nothing does not retrieve (KI-73) |
| Rerank | Ask whether the passage **answers** the question, graded (off-topic / related / partly / fully), batched | ✅ the answer-containment rubric, ranked by expected level (`retrieval/rerank.py`); the mean of the top 3 grades is the evidence gate |
| Context order | Best passages at the start **and** end (lost in the middle) | ✅ `order_for_lost_in_the_middle`; ids follow the new order |
| Whole-document questions | Document or section summaries retrieved for gist questions (RAPTOR / summary index) | ⚠️ section and document summaries built and retrieved (`8f0ec2b`); their effect on gist items not measured on its own |
| Generator prompt | Sources first, question last, numbered citations; read all sources; combine stated facts; resolve conflicts (later explanation wins); per-intent instructions | ✅ v5 + four per-intent blocks from the ingress intent; **Fast and Deep still get the base prompt only** (R2b) |
| Abstention | One clear sufficiency signal; few independent vetoes | ✅ floor before generation (`evidence_floor` 0.455: clearly absent → one corrective retrieval, then abstain; ADR-006) + the entity guard as defense-in-depth + IsUse after generation (Self-RAG): should-declines above the floor reach generation and are declined by the usefulness check, not the floor (`.data/evals/isuse-probe-a03a3a8.json`: failing answers ≤ 0.37, answerables ≥ 0.56); a streamed run is retracted first (`answer.retract`) |
| Usefulness (self critic) | Generation asked "is this helpful for the query", with grounding + relevance + support | ◐ IsUse covers grounding/relevance-vs-question (0.47 line); the reviewer covers support of individual claims; the old `sufficient` question failed calibration on both (findings 2026-10-17) |
| Degradation | An outage degrades the stage; it never fails the run | ✅ a decision outage takes each stage's own default — **the gate fails and abstains**, never answers; the sanitizer drops unanswered chunks so an outage cannot bypass it (KI-57) |
| Verification | Post-hoc claim check against cited passages | ✅ reviewer |
| Evaluation | Answer correctness and context recall on a labelled set, not only safety | ⚠️ answer correctness: content misses are a counted class, `MAX_CONTENT_MISSES = 1` (KI-75). Context recall: labelled answer chunks and recall@40 are R2a's next step, before any threshold work, then a `check-work` bar |
