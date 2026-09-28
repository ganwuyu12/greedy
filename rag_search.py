import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder


@dataclass
class Hit:
    text: str
    source: str
    score: float


class Retriever:
    def __init__(
        self,
        data_dir: Path,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        reranker_name: str = "BAAI/bge-reranker-base",
        use_rerank: bool = True,
    ) -> None:
        self.data_dir = data_dir
        self.model_name = model_name
        self.reranker_name = reranker_name
        self.use_rerank = use_rerank
        self._model = None
        self._reranker = None
        self._vectors = None
        self._chunks = None

    @property
    def model(self):
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def reranker(self):
        if self._reranker is None:
            self._reranker = CrossEncoder(self.reranker_name)
        return self._reranker

    def _ensure_loaded(self) -> None:
        if self._vectors is None:
            vectors = np.load(self.data_dir / "embeddings.npy")
            self._vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
            self._chunks = json.loads(
                (self.data_dir / "chunks.json").read_text(encoding="utf-8")
            )

    def search(self, query: str, top_k: int = 3, rerank_top_n: int = 20) -> list[Hit]:
        self._ensure_loaded()
        assert self._vectors is not None
        assert self._chunks is not None

        # 第一阶段：向量粗筛
        q = self.model.encode(query)
        q = q / np.linalg.norm(q)
        sims = self._vectors @ q
        n = rerank_top_n if self.use_rerank else top_k
        idx = np.argsort(sims)[::-1][:n]

        candidates = [
            Hit(
                text=self._chunks[i]["text"],
                source=self._chunks[i]["source"],
                score=float(sims[i]),
            )
            for i in idx
        ]

        # 第二阶段：rerank 精排
        if self.use_rerank:
            pairs = [(query, c.text) for c in candidates]
            scores = self.reranker.predict(pairs)
            for c, s in zip(candidates, scores):
                c.score = float(s)
            candidates.sort(key=lambda c: c.score, reverse=True)

        return candidates[:top_k]


if __name__ == '__main__':
    retriever = Retriever(Path("data/index"))
    results = retriever.search("1122D 怎么做的")
    for r in results:
        print(f"[{r.score:.3f}] {r.source}")
        print(r.text[:100])
        print("---")