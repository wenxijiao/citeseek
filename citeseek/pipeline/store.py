"""Upsert papers into SQLite and read them back as PaperMeta."""

from __future__ import annotations

import json
import sqlite3

from ..models import PaperMeta
from ..sources.base import normalize_title


def upsert_paper(conn: sqlite3.Connection, meta: PaperMeta) -> int:
    """Insert or merge a paper record; returns the paper id."""
    row = None
    if meta.arxiv_id:
        row = conn.execute("SELECT * FROM papers WHERE arxiv_id = ?", (meta.arxiv_id,)).fetchone()
    if row is None and meta.doi:
        row = conn.execute("SELECT * FROM papers WHERE doi = ?", (meta.doi,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM papers WHERE title_norm = ? AND abs(coalesce(year,0) - ?) <= 1",
            (normalize_title(meta.title), meta.year or 0),
        ).fetchone()

    if row is None:
        cur = conn.execute(
            """INSERT INTO papers (arxiv_id, doi, s2_id, openalex_id, title, title_norm,
                                   abstract, authors_json, year, venue, url, open_access,
                                   citation_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meta.arxiv_id,
                meta.doi,
                meta.s2_id,
                meta.openalex_id,
                meta.title,
                normalize_title(meta.title),
                meta.abstract,
                json.dumps(meta.authors),
                meta.year,
                meta.venue,
                meta.url,
                int(meta.open_access),
                meta.citation_count,
            ),
        )
        conn.commit()
        return cur.lastrowid

    # merge missing fields into the existing row
    updates: dict[str, object] = {}
    for col, val in (
        ("arxiv_id", meta.arxiv_id),
        ("doi", meta.doi),
        ("s2_id", meta.s2_id),
        ("openalex_id", meta.openalex_id),
        ("abstract", meta.abstract),
        ("year", meta.year),
        ("venue", meta.venue),
        ("url", meta.url),
        ("citation_count", meta.citation_count),
    ):
        if not row[col] and val:
            updates[col] = val
    if meta.open_access and not row["open_access"]:
        updates["open_access"] = 1
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE papers SET {sets} WHERE id = ?", (*updates.values(), row["id"]))
        conn.commit()
    return row["id"]


def get_paper(conn: sqlite3.Connection, paper_id: int) -> PaperMeta | None:
    row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return row_to_meta(row) if row else None


def row_to_meta(row: sqlite3.Row) -> PaperMeta:
    return PaperMeta(
        arxiv_id=row["arxiv_id"],
        doi=row["doi"],
        s2_id=row["s2_id"],
        openalex_id=row["openalex_id"],
        title=row["title"],
        abstract=row["abstract"],
        authors=json.loads(row["authors_json"] or "[]"),
        year=row["year"],
        venue=row["venue"],
        url=row["url"],
        open_access=bool(row["open_access"]),
        citation_count=row["citation_count"],
    )
