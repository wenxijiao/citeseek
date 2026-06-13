"""Semantic Scholar Graph API client.

Unauthenticated requests share a global ~1 req/s pool, so 429s are routine;
an S2_API_KEY (free) gives a dedicated 1 req/s.
"""

from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from ..models import PaperMeta
from .base import normalize_arxiv_id, normalize_doi
from .ratelimit import polite_get

logger = logging.getLogger(__name__)

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,venue,externalIds,citationCount,openAccessPdf,url,authors"


class SemanticScholarSource:
    name = "s2"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: str, limit: int = 25) -> list[PaperMeta]:
        headers = {}
        api_key = get_settings().s2_api_key
        if api_key:
            headers["x-api-key"] = api_key
        resp = await polite_get(
            self._client,
            API_URL,
            min_interval=1.1,
            params={"query": query, "limit": str(limit), "fields": FIELDS},
            headers=headers,
        )
        data = resp.json()

        papers = []
        for item in data.get("data") or []:
            ext = item.get("externalIds") or {}
            arxiv_id = ext.get("ArXiv")
            papers.append(
                PaperMeta(
                    arxiv_id=normalize_arxiv_id(arxiv_id) if arxiv_id else None,
                    doi=normalize_doi(ext.get("DOI")),
                    s2_id=item.get("paperId"),
                    title=item.get("title") or "",
                    abstract=item.get("abstract"),
                    authors=[a.get("name", "") for a in item.get("authors") or []],
                    year=item.get("year"),
                    venue=item.get("venue") or None,
                    url=item.get("url"),
                    open_access=bool(arxiv_id or item.get("openAccessPdf")),
                    citation_count=item.get("citationCount"),
                    sources=[self.name],
                )
            )
        return [p for p in papers if p.title]
