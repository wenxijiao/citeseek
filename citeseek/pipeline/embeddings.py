"""Local sentence embeddings (BAAI/bge-small-en-v1.5, 384-dim).

The model is lazy-loaded on first use and cached under var/models/.
Vectors are L2-normalized so cosine similarity == dot product.
bge models require a query-side instruction prefix for retrieval.
"""

from __future__ import annotations

import os

import numpy as np

from ..config import get_settings
from ..db import EMBEDDING_DIM

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# HF progress bars write to stdout, which corrupts MCP stdio transport.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


class Embedder:
    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            settings = get_settings()
            settings.models_dir.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(
                MODEL_NAME, cache_folder=str(settings.models_dir)
            )
        return self._model

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32
        )
        return np.asarray(vecs, dtype=np.float32).reshape(len(texts), EMBEDDING_DIM)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([QUERY_PREFIX + text])[0]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
