"""arXiv Atom API client. No key; be polite: 1 request / 3 s."""

from __future__ import annotations

import logging

import feedparser
import httpx

from ..models import PaperMeta
from .base import normalize_arxiv_id
from .ratelimit import SourceError, polite_get

logger = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"


class ArxivSource:
    name = "arxiv"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: str, limit: int = 25) -> list[PaperMeta]:
        # Exact-phrase search on a whole sentence finds nothing; AND the
        # terms instead (cap the count to keep the query sane).
        terms = query.split()
        if len(terms) > 1:
            search_query = " AND ".join(f"all:{t}" for t in terms[:8])
        else:
            search_query = f"all:{query}"
        params = {
            "search_query": search_query,
            "max_results": str(limit),
            "sortBy": "relevance",
        }
        resp = await polite_get(self._client, API_URL, min_interval=3.0, params=params)
        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            raise SourceError(f"arxiv: unparseable feed ({feed.bozo_exception})")

        papers = []
        for entry in feed.entries:
            arxiv_id = normalize_arxiv_id(entry.get("id", ""))
            if not arxiv_id:
                continue
            year = None
            if entry.get("published_parsed"):
                year = entry.published_parsed.tm_year
            doi = entry.get("arxiv_doi")
            papers.append(
                PaperMeta(
                    arxiv_id=arxiv_id,
                    doi=doi,
                    title=" ".join(entry.get("title", "").split()),
                    abstract=" ".join(entry.get("summary", "").split()) or None,
                    authors=[a.get("name", "") for a in entry.get("authors", [])],
                    year=year,
                    venue=entry.get("arxiv_journal_ref"),
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    open_access=True,
                    sources=[self.name],
                )
            )
        return papers
