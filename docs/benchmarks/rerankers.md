# Reranker comparison

Generated 2026-10-20 21:13 UTC at commit `3ab3510` by `scripts/compare_rerankers.py`.
Pools: the recorded retrieval queries of `20261018-195514.json` replayed through `hybrid_search` (fused top 40); every reranker saw the identical pool.
Labels: `evals/acceptance/answer_passages.json` (gist items: any passage of the document). Differences under 2 items are ties.

| reranker | recall@8 | nDCG@10 | p50 ms | p95 ms | $ / 1k queries | cost source |
|---|---|---|---|---|---|---|
| jev | 31/33 (0.939) | 0.7056 | 670 | 836 | 1.162 | OpenRouter generation stats |
| cohere | 26/33 (0.788) | 0.5872 | 526 | 767 | 2.0 | price table |
| nvidia | 27/33 (0.818) | 0.5564 | 870 | 1254 | 0.0 | price table |
| bge | 25/33 (0.758) | 0.551 | 8610 | 14496 | 0.0 | price table |
| fused | 26/33 (0.788) | 0.4895 | 0 | 0 | 0.0 | price table |

## Paired against Jev (recall@8 per item)

| reranker | wins | losses | verdict | losses (items) |
|---|---|---|---|---|
| cohere | 1 | 6 | worse | character-collins, frame-walton, ml-es-rocinante, ml-fr-bovary-death, plot-red-headed-league, xl-en-bovary-death |
| nvidia | 1 | 5 | worse | frame-walton, ml-es-rocinante, ml-fr-bovary-death, plot-red-headed-league, xl-en-bovary-death |
| bge | 1 | 7 | worse | character-collins, followup-adler, frame-walton, ml-es-rocinante, ml-fr-bovary-death, plot-red-headed-league, xl-en-bovary-death |
| fused | 1 | 6 | worse | fact-bennet-sisters, frame-walton, ml-zh-wukong-weapon, ml-zh-xiyou-nezha, plot-red-headed-league, xl-en-bovary-death |
