"""Backward snowballing: expand the candidate pool with seed references.

Metadata keyword search systematically buries famous antecedent papers under
their own follow-up work: a query about residual connections returns hundreds
of papers that *cite* ResNet before it returns ResNet. Those follow-up papers
all carry the antecedent in their reference lists, so the most claim-similar
candidates ("seeds") are mined for references and the references join the
candidate pool. The number of distinct seeds citing a reference is returned
as a ranking signal (seed-citation frequency): a paper cited by most of the
seeds is very likely the shared antecedent.

OpenAlex is the primary source (generous rate limits; one call for the id
list, batched calls to resolve metadata). Semantic Scholar is the fallback
for arXiv-only seeds that OpenAlex cannot resolve.
"""

from __future__ import annotations

import logging
import re

import httpx

from ..config import get_settings
from ..models import PaperMeta, StageEvent
from ..sources.base import normalize_arxiv_id, normalize_doi, normalize_title
from ..sources.openalex import SELECT as OPENALEX_SELECT
from ..sources.openalex import parse_work
from ..sources.ratelimit import SourceError, polite_get

logger = logging.getLogger(__name__)

OPENALEX_WORKS = "https://api.openalex.org/works"
S2_REFS = "https://api.semanticscholar.org/graph/v1/paper/{pid}/references"
S2_FIELDS = "title,abstract,year,venue,externalIds,citationCount,openAccessPdf,url,authors"


def meta_key(meta: PaperMeta) -> str:
    """Stable identity used for seed-citation frequency counting."""
    if meta.arxiv_id:
        return f"arxiv:{meta.arxiv_id}"
    if meta.doi:
        doi = meta.doi
        if doi.startswith("10.48550/arxiv."):
            return f"arxiv:{doi.removeprefix('10.48550/arxiv.')}"
        return f"doi:{doi}"
    return f"title:{normalize_title(meta.title)}"


class SeedCitationIndex:
    """Lookup of seed-citation counts with fuzzy-title aggregation.

    Scholarly citation graphs split one paper across several metadata
    records (preprint, proceedings, reprint, no-id stubs — often with
    wrong years), so citation credit for a famous antecedent gets divided
    between records that exact-id matching cannot reunite. Counts from
    records with near-identical normalized titles are therefore summed,
    unless both records carry (different) arXiv ids — those are genuinely
    distinct papers.
    """

    def __init__(
        self, refs: list[PaperMeta], freq: dict[str, int], threshold: int = 92
    ) -> None:
        from rapidfuzz import fuzz

        self._fuzz = fuzz
        self._freq = freq
        self._threshold = threshold
        self._entries = [
            (normalize_title(r.title), bool(r.arxiv_id), meta_key(r), freq.get(meta_key(r), 0))
            for r in refs
            if freq.get(meta_key(r), 0) > 0
        ]

    def count_for(self, meta: PaperMeta) -> int:
        own_key = meta_key(meta)
        count = self._freq.get(own_key, 0)
        title = normalize_title(meta.title)
        if not title:
            return count
        for ref_title, ref_has_arxiv, ref_key, ref_count in self._entries:
            if ref_key == own_key:
                continue
            if ref_has_arxiv and meta.arxiv_id:
                continue  # two distinct arXiv ids -> different papers
            if self._fuzz.token_sort_ratio(title, ref_title) >= self._threshold:
                count += ref_count
        return count


def _openalex_params(extra: dict | None = None) -> dict:
    params = dict(extra or {})
    mailto = get_settings().openalex_mailto
    if mailto:
        params["mailto"] = mailto
    return params


async def _openalex_referenced_ids(client: httpx.AsyncClient, seed: PaperMeta) -> list[str]:
    """Return the OpenAlex work ids referenced by a seed paper."""
    if seed.openalex_id:
        key = seed.openalex_id
    elif seed.doi:
        key = f"https://doi.org/{seed.doi}"
    elif seed.arxiv_id:
        key = f"https://doi.org/10.48550/arxiv.{seed.arxiv_id}"
    else:
        return []
    resp = await polite_get(
        client,
        f"{OPENALEX_WORKS}/{key}",
        min_interval=0.2,
        params=_openalex_params({"select": "referenced_works"}),
    )
    refs = resp.json().get("referenced_works") or []
    return [r.rsplit("/", 1)[-1] for r in refs]


async def _openalex_resolve(
    client: httpx.AsyncClient, work_ids: list[str], batch: int = 50
) -> list[PaperMeta]:
    """Resolve OpenAlex work ids to metadata in batched OR-filter calls."""
    metas: list[PaperMeta] = []
    for i in range(0, len(work_ids), batch):
        chunk = work_ids[i : i + batch]
        resp = await polite_get(
            client,
            OPENALEX_WORKS,
            min_interval=0.2,
            params=_openalex_params({
                "filter": f"openalex_id:{'|'.join(chunk)}",
                "select": OPENALEX_SELECT,
                "per-page": str(batch),
            }),
        )
        metas.extend(
            parse_work(item, "openalex-ref") for item in resp.json().get("results") or []
        )
    return [m for m in metas if m.title]


_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


async def _s2_references(client: httpx.AsyncClient, seed: PaperMeta) -> list[PaperMeta]:
    """Fallback: one Semantic Scholar call returns reference metadata directly."""
    if seed.arxiv_id and _ARXIV_ID.match(seed.arxiv_id):
        pid = f"arXiv:{seed.arxiv_id}"
    elif seed.doi:
        pid = f"DOI:{seed.doi}"
    elif seed.s2_id:
        pid = seed.s2_id
    else:
        return []
    headers = {}
    api_key = get_settings().s2_api_key
    if api_key:
        headers["x-api-key"] = api_key
    resp = await polite_get(
        client,
        S2_REFS.format(pid=pid),
        min_interval=1.1,
        params={"fields": S2_FIELDS, "limit": "100"},
        headers=headers,
    )
    metas = []
    for row in resp.json().get("data") or []:
        item = row.get("citedPaper") or {}
        if not item.get("title"):
            continue
        ext = item.get("externalIds") or {}
        arxiv_id = ext.get("ArXiv")
        metas.append(
            PaperMeta(
                arxiv_id=normalize_arxiv_id(arxiv_id) if arxiv_id else None,
                doi=normalize_doi(ext.get("DOI")),
                s2_id=item.get("paperId"),
                title=item["title"],
                abstract=item.get("abstract"),
                authors=[a.get("name", "") for a in item.get("authors") or []],
                year=item.get("year"),
                venue=item.get("venue") or None,
                url=item.get("url"),
                open_access=bool(arxiv_id or item.get("openAccessPdf")),
                citation_count=item.get("citationCount"),
                sources=["s2-ref"],
            )
        )
    return metas


async def fetch_seed_references(
    client: httpx.AsyncClient, seed: PaperMeta, per_seed: int = 100
) -> list[PaperMeta]:
    """References of one seed paper; OpenAlex first, Semantic Scholar fallback."""
    try:
        ids = await _openalex_referenced_ids(client, seed)
        if ids:
            return await _openalex_resolve(client, ids[:per_seed])
    except (SourceError, httpx.HTTPError) as exc:
        logger.warning("openalex references failed for %r: %s", seed.title[:50], exc)
    try:
        return (await _s2_references(client, seed))[:per_seed]
    except (SourceError, httpx.HTTPError) as exc:
        logger.warning("s2 references failed for %r: %s", seed.title[:50], exc)
    return []


async def expand_with_references(
    client: httpx.AsyncClient,
    seeds: list[PaperMeta],
    *,
    per_seed: int = 100,
    emit=None,
) -> tuple[list[PaperMeta], dict[str, int]]:
    """Mine the references of seed papers.

    Returns (unique reference metas, seed-citation frequency by meta_key).
    Seeds should be the candidates most similar to the claim (caller ranks).
    """
    freq: dict[str, int] = {}
    by_key: dict[str, PaperMeta] = {}
    for i, seed in enumerate(seeds):
        refs = await fetch_seed_references(client, seed, per_seed=per_seed)
        seen_this_seed: set[str] = set()
        for ref in refs:
            key = meta_key(ref)
            if key in seen_this_seed:
                continue
            seen_this_seed.add(key)
            freq[key] = freq.get(key, 0) + 1
            if key not in by_key:
                by_key[key] = ref
        if emit is not None:
            await emit(
                StageEvent(
                    stage="citations",
                    detail=f"seed {i + 1}/{len(seeds)}: {len(refs)} references",
                )
            )
    return list(by_key.values()), freq
