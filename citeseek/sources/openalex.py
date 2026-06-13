"""OpenAlex works API client. Free; a mailto joins the polite pool."""

from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from ..models import PaperMeta
from .base import normalize_arxiv_id, normalize_doi
from .ratelimit import polite_get

logger = logging.getLogger(__name__)

API_URL = "https://api.openalex.org/works"
SELECT = (
    "id,doi,title,publication_year,primary_location,open_access,"
    "authorships,cited_by_count,abstract_inverted_index,ids"
)


def deinvert_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        positions.extend((i, word) for i in idxs)
    positions.sort()
    return " ".join(word for _, word in positions) or None


def parse_work(item: dict, source_name: str = "openalex") -> PaperMeta:
    """Build a PaperMeta from one OpenAlex work object."""
    ids = item.get("ids") or {}
    arxiv_url = None
    loc = item.get("primary_location") or {}
    src = loc.get("source") or {}
    if "arxiv" in (src.get("display_name") or "").lower():
        arxiv_url = loc.get("landing_page_url")
    oa = item.get("open_access") or {}
    return PaperMeta(
        arxiv_id=normalize_arxiv_id(arxiv_url) if arxiv_url else None,
        doi=normalize_doi(item.get("doi")),
        openalex_id=(ids.get("openalex") or "").rsplit("/", 1)[-1] or None,
        title=item.get("title") or "",
        abstract=deinvert_abstract(item.get("abstract_inverted_index")),
        authors=[
            (a.get("author") or {}).get("display_name", "")
            for a in item.get("authorships") or []
        ],
        year=item.get("publication_year"),
        venue=src.get("display_name"),
        url=item.get("doi") or loc.get("landing_page_url"),
        open_access=bool(oa.get("is_oa")),
        citation_count=item.get("cited_by_count"),
        sources=[source_name],
    )


class OpenAlexSource:
    name = "openalex"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: str, limit: int = 25) -> list[PaperMeta]:
        params = {"search": query, "per-page": str(limit), "select": SELECT}
        mailto = get_settings().openalex_mailto
        if mailto:
            params["mailto"] = mailto
        resp = await polite_get(self._client, API_URL, min_interval=0.2, params=params)
        data = resp.json()
        papers = [parse_work(item, self.name) for item in data.get("results") or []]
        return [p for p in papers if p.title]
