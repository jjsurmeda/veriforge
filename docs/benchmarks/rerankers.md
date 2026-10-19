# Reranker comparison

Generated 2026-10-19 19:22 UTC at commit `55393ad` by `scripts/compare_rerankers.py`.
Pools: the recorded retrieval queries of `20261018-195514.json` replayed through `hybrid_search` (fused top 40); every reranker saw the identical pool.
Labels: `evals/acceptance/answer_passages.json` (gist items: any passage of the document). Differences under 2 items are ties.

| reranker | recall@8 | nDCG@10 | p50 ms | p95 ms | $ / 1k queries | cost source |
|---|---|---|---|---|---|---|
| jev | 31/33 (0.939) | 0.7046 | 631 | 848 | 1.1621 | OpenRouter generation stats |
| nvidia | 27/33 (0.818) | 0.5564 | 852 | 1228 | 0.0 | price table |
| fused | 26/33 (0.788) | 0.4877 | 0 | 0 | 0.0 | price table |

## Paired against Jev (recall@8 per item)

| reranker | wins | losses | verdict | losses (items) |
|---|---|---|---|---|
| nvidia | 1 | 5 | worse | frame-walton, ml-es-rocinante, ml-fr-bovary-death, plot-red-headed-league, xl-en-bovary-death |
| fused | 1 | 6 | worse | fact-bennet-sisters, frame-walton, ml-zh-wukong-weapon, ml-zh-xiyou-nezha, plot-red-headed-league, xl-en-bovary-death |
