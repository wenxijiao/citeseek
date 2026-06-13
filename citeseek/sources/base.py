from __future__ import annotations

from typing import Protocol

import httpx

from ..models import PaperMeta


class SourceClient(Protocol):
    """A scholarly metadata source."""

    name: str

    def __init__(self, client: httpx.AsyncClient) -> None: ...

    async def search(self, query: str, limit: int = 25) -> list[PaperMeta]: ...


def normalize_arxiv_id(raw: str) -> str:
    """'2104.08691v2' / 'arXiv:2104.08691' / abs URL -> '2104.08691'."""
    s = raw.strip()
    for prefix in ("arXiv:", "arxiv:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    if "arxiv.org" in s:
        s = s.rstrip("/").split("/")[-1]
    if s.endswith(".pdf"):
        s = s[: -len(".pdf")]
    # strip version suffix
    if "v" in s:
        head, _, tail = s.rpartition("v")
        if head and tail.isdigit():
            s = head
    return s


def normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s or None


def normalize_title(title: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation/LaTeX braces for fuzzy matching."""
    import re

    s = title.lower()
    s = re.sub(r"[\\{}$^_]", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()
