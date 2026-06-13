"""Full-text resolution chain: arxiv.org/html -> ar5iv -> PDF.

Raw files are cached in var/fulltext/, parsed documents in the documents
table. Only arXiv-hosted papers have fetchable full text; everything else
stays metadata-only (the UI degrades gracefully).
"""

from __future__ import annotations

import logging
import sqlite3

import httpx

from ..config import get_settings
from ..models import ParsedDoc
from ..sources.ratelimit import polite_get
from .html_parser import parse_latexml_html
from .pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


async def _try_html(client: httpx.AsyncClient, url: str, fmt: str) -> ParsedDoc | None:
    try:
        resp = await polite_get(client, url, min_interval=1.0, max_retries=1, timeout=15.0)
        doc = parse_latexml_html(resp.text, fmt=fmt)
        doc.source_url = url
        return doc
    except Exception as exc:
        logger.info("%s failed: %s", url, exc)
        return None


async def fetch_fulltext(
    client: httpx.AsyncClient, arxiv_id: str
) -> ParsedDoc | None:
    """Fetch and parse full text for an arXiv paper, or None."""
    doc = await _try_html(client, f"https://arxiv.org/html/{arxiv_id}", "arxiv_html")
    if doc is None:
        doc = await _try_html(
            client, f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}", "ar5iv"
        )
    if doc is None:
        try:
            resp = await polite_get(
                client,
                f"https://arxiv.org/pdf/{arxiv_id}",
                min_interval=1.0,
                max_retries=1,
                timeout=30.0,
            )
            doc = parse_pdf(resp.content)
            doc.source_url = f"https://arxiv.org/pdf/{arxiv_id}"
        except Exception as exc:
            logger.warning("PDF fallback failed for %s: %s", arxiv_id, exc)
            return None

    settings = get_settings()
    settings.fulltext_dir.mkdir(parents=True, exist_ok=True)
    (settings.fulltext_dir / f"{arxiv_id.replace('/', '_')}.txt").write_text(
        doc.plain_text
    )
    return doc


def save_document(conn: sqlite3.Connection, paper_id: int, doc: ParsedDoc) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO documents (paper_id, reader_html, plain_text, source_url)
           VALUES (?, ?, ?, ?)""",
        (paper_id, doc.reader_html, doc.plain_text, doc.source_url),
    )
    conn.execute(
        "UPDATE papers SET fulltext_status = 'parsed', fulltext_format = ? WHERE id = ?",
        (doc.format, paper_id),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, paper_id: int) -> None:
    conn.execute("UPDATE papers SET fulltext_status = 'failed' WHERE id = ?", (paper_id,))
    conn.commit()


def get_document(conn: sqlite3.Connection, paper_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE paper_id = ?", (paper_id,)
    ).fetchone()
