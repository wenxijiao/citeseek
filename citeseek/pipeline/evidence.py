"""Stage 5-6: fetch full text for top candidates and retrieve evidence passages."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import get_settings
from ..db import Connection
from ..fetch.fulltext import fetch_fulltext, get_document, mark_failed, save_document
from ..models import Candidate, ParsedDoc, Passage, StageEvent
from .chunking import chunk_document
from .embeddings import get_embedder
from .index import VectorIndex
from .rank import EmitFn, _noop_emit

logger = logging.getLogger(__name__)


def index_document(conn: Connection, paper_id: int, doc: ParsedDoc) -> None:
    """Chunk, embed, and store a parsed document (idempotent per paper)."""
    existing = conn.execute(
        "SELECT count(*) FROM chunks WHERE paper_id = ?", (paper_id,)
    ).fetchone()[0]
    if existing:
        return
    chunks = chunk_document(doc)
    if not chunks:
        return
    cur_ids = []
    for chunk in chunks:
        cur = conn.execute(
            "INSERT INTO chunks (paper_id, ord, section, para_start, para_end, text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (paper_id, chunk.ord, chunk.section, chunk.para_start, chunk.para_end, chunk.text),
        )
        cur_ids.append(cur.lastrowid)
    conn.commit()
    vecs = get_embedder().embed_passages([c.text for c in chunks])
    VectorIndex(conn).upsert_chunk_vecs(paper_id, cur_ids, vecs)


async def ensure_fulltext(
    conn: Connection, client: httpx.AsyncClient, paper_id: int
) -> bool:
    """Fetch+parse+index full text for one paper if possible. True if available."""
    row = conn.execute(
        "SELECT arxiv_id, fulltext_status FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    if row is None:
        return False
    if row["fulltext_status"] == "parsed":
        return True
    if row["fulltext_status"] == "failed" or not row["arxiv_id"]:
        return False
    doc = await fetch_fulltext(client, row["arxiv_id"])
    if doc is None:
        mark_failed(conn, paper_id)
        return False
    save_document(conn, paper_id, doc)
    await asyncio.to_thread(index_document, conn, paper_id, doc)
    return True


async def attach_evidence(
    conn: Connection,
    claim: str,
    candidates: list[Candidate],
    *,
    emit: EmitFn = _noop_emit,
    top_n: int | None = None,
) -> list[Candidate]:
    """Fetch full text for the top-N open-access candidates and attach the
    best-matching passages to each. Mutates and returns candidates."""
    settings = get_settings()
    top_n = top_n or settings.fulltext_top_n
    targets = [c for c in candidates if c.paper.arxiv_id][:top_n]
    if not targets:
        return candidates

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for cand in targets:
            await emit(
                StageEvent(
                    stage="fulltext",
                    detail=f"Fetching {cand.paper.arxiv_id}: {cand.paper.title[:60]}",
                )
            )
            ok = await ensure_fulltext(conn, client, cand.paper_id)
            if not ok:
                await emit(
                    StageEvent(stage="fulltext", detail=f"{cand.paper.arxiv_id}: unavailable")
                )

    await emit(StageEvent(stage="passages", detail="Retrieving evidence passages"))
    qvec = await asyncio.to_thread(get_embedder().embed_query, claim)
    index = VectorIndex(conn)
    by_paper = index.search_chunks(
        qvec, [c.paper_id for c in targets], k_per_paper=settings.passages_per_paper
    )
    for cand in targets:
        hits = by_paper.get(cand.paper_id, [])
        if not hits:
            continue
        placeholders = ",".join("?" * len(hits))
        rows = conn.execute(
            f"SELECT id, section, text FROM chunks WHERE id IN ({placeholders})",
            [chunk_id for chunk_id, _ in hits],
        ).fetchall()
        text_by_id = {r["id"]: r for r in rows}
        cand.passages = [
            Passage(
                chunk_id=chunk_id,
                section=text_by_id[chunk_id]["section"],
                quote=text_by_id[chunk_id]["text"],
                score=score,
            )
            for chunk_id, score in hits
            if chunk_id in text_by_id
        ]
    return candidates
