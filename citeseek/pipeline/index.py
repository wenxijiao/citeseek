"""Vector storage and similarity search.

Embeddings always live in plain BLOB tables (source of truth); when the
sqlite-vec extension is available they are mirrored into vec0 virtual
tables for indexed search, otherwise we brute-force with numpy. At this
project's scale (<=1e5 chunks) both are fast.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from ..db import EMBEDDING_DIM


def _to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class VectorIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._vec = getattr(conn, "vec_enabled", False)

    def upsert_paper_vec(self, paper_id: int, vec: np.ndarray) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO paper_embeddings (paper_id, embedding) VALUES (?, ?)",
            (paper_id, _to_blob(vec)),
        )
        if self._vec:
            self._conn.execute("DELETE FROM paper_vecs WHERE paper_id = ?", (paper_id,))
            self._conn.execute(
                "INSERT INTO paper_vecs (paper_id, embedding) VALUES (?, ?)",
                (paper_id, _to_blob(vec)),
            )
        self._conn.commit()

    def has_paper_vec(self, paper_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM paper_embeddings WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        return row is not None

    def upsert_chunk_vecs(self, paper_id: int, chunk_ids: list[int], vecs: np.ndarray) -> None:
        rows = [(cid, paper_id, _to_blob(v)) for cid, v in zip(chunk_ids, vecs)]
        self._conn.executemany(
            "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, paper_id, embedding) VALUES (?, ?, ?)",
            rows,
        )
        if self._vec:
            self._conn.executemany(
                "DELETE FROM chunk_vecs WHERE chunk_id = ?", [(cid,) for cid in chunk_ids]
            )
            self._conn.executemany(
                "INSERT INTO chunk_vecs (chunk_id, embedding) VALUES (?, ?)",
                [(cid, _to_blob(v)) for cid, v in zip(chunk_ids, vecs)],
            )
        self._conn.commit()

    def score_papers(self, qvec: np.ndarray, paper_ids: list[int]) -> dict[int, float]:
        """Cosine similarity of the query against specific papers."""
        if not paper_ids:
            return {}
        placeholders = ",".join("?" * len(paper_ids))
        rows = self._conn.execute(
            f"SELECT paper_id, embedding FROM paper_embeddings WHERE paper_id IN ({placeholders})",
            paper_ids,
        ).fetchall()
        q = np.asarray(qvec, dtype=np.float32)
        return {row["paper_id"]: float(_from_blob(row["embedding"]) @ q) for row in rows}

    def search_chunks(
        self, qvec: np.ndarray, paper_ids: list[int], k_per_paper: int = 3
    ) -> dict[int, list[tuple[int, float]]]:
        """Top-k chunks per paper: {paper_id: [(chunk_id, score), ...]}."""
        if not paper_ids:
            return {}
        placeholders = ",".join("?" * len(paper_ids))
        rows = self._conn.execute(
            f"SELECT chunk_id, paper_id, embedding FROM chunk_embeddings "
            f"WHERE paper_id IN ({placeholders})",
            paper_ids,
        ).fetchall()
        q = np.asarray(qvec, dtype=np.float32)
        by_paper: dict[int, list[tuple[int, float]]] = {}
        for row in rows:
            score = float(_from_blob(row["embedding"]) @ q)
            by_paper.setdefault(row["paper_id"], []).append((row["chunk_id"], score))
        return {
            pid: sorted(pairs, key=lambda p: -p[1])[:k_per_paper]
            for pid, pairs in by_paper.items()
        }


def embedding_dim_ok(vec: np.ndarray) -> bool:
    return vec.shape[-1] == EMBEDDING_DIM
