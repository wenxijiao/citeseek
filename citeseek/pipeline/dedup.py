"""Merge duplicate papers returned by different sources/queries.

Pass 1 keys on arXiv id, then DOI (arXiv-assigned 10.48550 DOIs and
publisher DOIs differ for the same paper, so the title pass still matters).
Pass 2 fuzzy-merges on normalized title (token_sort_ratio >= 95) when the
years are within 1 of each other.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from ..models import PaperMeta
from ..sources.base import normalize_title


def _merge(a: PaperMeta, b: PaperMeta) -> PaperMeta:
    """Keep the most complete information from both records."""
    merged = a.model_copy()
    for field in ("arxiv_id", "doi", "s2_id", "openalex_id", "abstract", "venue", "url", "year"):
        if getattr(merged, field) in (None, "") and getattr(b, field) not in (None, ""):
            setattr(merged, field, getattr(b, field))
    if len(b.authors) > len(merged.authors):
        merged.authors = b.authors
    if (b.citation_count or 0) > (merged.citation_count or 0):
        merged.citation_count = b.citation_count
    merged.open_access = merged.open_access or b.open_access
    merged.sources = sorted(set(merged.sources) | set(b.sources))
    return merged


def dedupe(metas: list[PaperMeta]) -> list[PaperMeta]:
    by_key: dict[str, PaperMeta] = {}
    keyless: list[PaperMeta] = []

    for meta in metas:
        key = None
        if meta.arxiv_id:
            key = f"arxiv:{meta.arxiv_id}"
        elif meta.doi:
            key = f"doi:{meta.doi}"
        if key is None:
            keyless.append(meta)
        elif key in by_key:
            by_key[key] = _merge(by_key[key], meta)
        else:
            by_key[key] = meta

    # Second pass: fuzzy title merge of keyless records (and keyed records
    # that share a title but used different key namespaces).
    result: list[PaperMeta] = list(by_key.values())
    for meta in keyless:
        title_norm = normalize_title(meta.title)
        merged_into = None
        for i, existing in enumerate(result):
            if abs((meta.year or 0) - (existing.year or 0)) > 1:
                continue
            if fuzz.token_sort_ratio(title_norm, normalize_title(existing.title)) >= 95:
                merged_into = i
                break
        if merged_into is None:
            result.append(meta)
        else:
            result[merged_into] = _merge(result[merged_into], meta)

    # Cross-namespace fuzzy pass over keyed records (arxiv-keyed vs doi-keyed).
    final: list[PaperMeta] = []
    for meta in result:
        title_norm = normalize_title(meta.title)
        merged_into = None
        for i, existing in enumerate(final):
            same_ns = (meta.arxiv_id and existing.arxiv_id) or (
                meta.doi and existing.doi and not (meta.arxiv_id or existing.arxiv_id)
            )
            if same_ns:
                continue  # pass 1 already decided these are distinct
            if abs((meta.year or 0) - (existing.year or 0)) > 1:
                continue
            if fuzz.token_sort_ratio(title_norm, normalize_title(existing.title)) >= 95:
                merged_into = i
                break
        if merged_into is None:
            final.append(meta)
        else:
            final[merged_into] = _merge(final[merged_into], meta)
    return final
