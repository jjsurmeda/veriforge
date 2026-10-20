"""Open-weight rerankers run on this machine, for comparison scripts only.

Not in the product registry (`retrieval.rerank.RERANKERS`) on purpose: the app
image carries no PyTorch and `GET /rerankers` must only list what a run can use.
`sentence-transformers` is not a project dependency; run the script with it:

    uv run --with sentence-transformers python -m scripts.compare_rerankers ... --ids jev,bge
"""

import asyncio
import importlib.util
from typing import Any

from retrieval.rerank import RerankerInfo, RerankResult

BGE_MODEL = "BAAI/bge-reranker-v2-m3"  # Apache 2.0, 568M params, multilingual


class BgeLocalRerank:
    reranker_id = "bge"

    def __init__(self, model: str = BGE_MODEL) -> None:
        self._name = model
        self._model: Any = None

    async def rerank(self, *, query: str, documents: list[str], top_n: int) -> RerankResult:
        if not documents:
            return []
        scores = await asyncio.to_thread(self._score, query, documents)
        order = sorted(range(len(documents)), key=lambda i: (-scores[i], i))  # ties: input order
        return [(i, float(scores[i])) for i in order[:top_n]]

    def _score(self, query: str, documents: list[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

            self._model = CrossEncoder(self._name, max_length=512)
        return [float(s) for s in self._model.predict([(query, d) for d in documents])]


BGE_INFO = RerankerInfo(
    "bge",
    "BGE reranker v2 m3 (local)",
    "traditional",
    0.0,
    "open weights run locally: no API cost; compute and hosting not included",
    lambda s: importlib.util.find_spec("sentence_transformers") is not None,
    lambda s, e, r: BgeLocalRerank(),
)
