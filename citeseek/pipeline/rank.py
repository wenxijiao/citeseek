"""The staged retrieval/ranking pipeline.

Every stage reports progress through ``emit(StageEvent)`` — the same
contract feeds the SSE stream (web), MCP progress, and the CLI spinner.
Stages degrade gracefully: a failed source or a missing LLM key reduces
quality but never fails the run.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

import httpx

from ..config import get_settings
from ..db import Connection
from ..models import Candidate, CandidateScores, PaperMeta, StageEvent
from ..sources import ALL_SOURCES
from .dedup import dedupe
from .embeddings import get_embedder
from .index import VectorIndex
from .store import upsert_paper

logger = logging.getLogger(__name__)

EmitFn = Callable[[StageEvent], Awaitable[None]]

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or that the
    their this to was we were which with our can may such using based propose proposed
    show shows new novel""".split()
)


async def _noop_emit(event: StageEvent) -> None:
    return None


def fallback_queries(claim: str) -> list[str]:
    """No-LLM degradation: the claim, a stopword-stripped variant, and a short
    keyword query (rare terms first — long AND queries miss paraphrases)."""
    words = [w for w in re.findall(r"[\w-]+", claim.lower()) if w not in _STOPWORDS]
    stripped = " ".join(words[:10])
    # prefer distinctive terms: longer words first, preserve original order on ties
    distinctive = sorted(set(words), key=lambda w: -len(w))[:5]
    short = " ".join(w for w in words if w in distinctive)
    queries = [claim.strip()]
    if stripped and stripped != claim.strip().lower():
        queries.append(stripped)
    if short and short not in (stripped, claim.strip().lower()):
        queries.append(short)
    return queries


async def search_sources(
    client: httpx.AsyncClient, queries: list[str], emit: EmitFn, limit: int = 25
) -> list[PaperMeta]:
    """Fan out every query to every source; tolerate individual failures."""
    sources = [cls(client) for cls in ALL_SOURCES]

    async def one(source, query: str) -> list[PaperMeta]:
        try:
            results = await source.search(query, limit=limit)
            await emit(
                StageEvent(
                    stage="search",
                    detail=f"{source.name}: {len(results)} results",
                    payload={"source": source.name, "query": query, "count": len(results)},
                )
            )
            return results
        except Exception as exc:
            logger.warning("source %s failed for %r: %s", source.name, query, exc)
            await emit(
                StageEvent(stage="search", detail=f"{source.name} failed ({exc})")
            )
            return []

    batches = await asyncio.gather(*(one(s, q) for s in sources for q in queries))
    return [meta for batch in batches for meta in batch]


async def first_pass_rank(
    conn: Connection,
    claim: str,
    metas: list[PaperMeta],
    keep: int,
    cite_index=None,
) -> list[Candidate]:
    """Embed title+abstract, score against the claim, keep the best.

    ``cite_index`` is the SeedCitationIndex from backward snowballing
    (pipeline.citations): papers cited by many of the claim's most similar
    candidates get a bonus of up to W_CITE.
    """
    embedder = get_embedder()
    index = VectorIndex(conn)
    qvec = await asyncio.to_thread(embedder.embed_query, claim)

    paper_ids: list[int] = []
    id_to_meta: dict[int, PaperMeta] = {}
    sources_by_id: dict[int, list[str]] = {}
    for meta in metas:
        pid = upsert_paper(conn, meta)
        paper_ids.append(pid)
        id_to_meta[pid] = meta
        sources_by_id[pid] = meta.sources

    missing = [pid for pid in id_to_meta if not index.has_paper_vec(pid)]
    if missing:
        texts = [
            f"{id_to_meta[pid].title}. {id_to_meta[pid].abstract or ''}".strip()
            for pid in missing
        ]
        vecs = await asyncio.to_thread(embedder.embed_passages, texts)
        for pid, vec in zip(missing, vecs):
            index.upsert_paper_vec(pid, vec)

    scores = index.score_papers(qvec, list(id_to_meta))
    cite_bonus: dict[int, float] = {}
    if cite_index is not None:
        for pid, meta in id_to_meta.items():
            count = min(cite_index.count_for(meta), 10)
            if count and pid in scores:
                cite_bonus[pid] = W_CITE * count / 10
                scores[pid] += cite_bonus[pid]
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:keep]
    return [
        Candidate(
            rank=i + 1,
            paper_id=pid,
            paper=id_to_meta[pid].model_copy(update={"sources": sources_by_id.get(pid, [])}),
            scores=CandidateScores(
                embed=score - cite_bonus.get(pid, 0.0),
                cite_freq=cite_bonus.get(pid) or None,
                final=score,
            ),
        )
        for i, (pid, score) in enumerate(ranked)
    ]


W_EMBED, W_LLM, W_YEAR, W_CITE, W_SURVEY = 0.4, 0.6, 0.05, 0.3, 0.08

_SURVEY_TITLE = re.compile(
    r"\b(survey|review|overview|tutorial|introduction to|outlook|advances in)\b",
    re.IGNORECASE,
)


def finalize_scores(
    candidates: list[Candidate], *, before_year: int | None = None, use_year_prior: bool = True
) -> list[Candidate]:
    """Combine embedding similarity, LLM confidence, and a mild year prior.

    The year prior favors earlier papers (antecedent-oriented ranking); when
    before_year is known (the year of the paper being read), papers published
    after it get no prior at all. Survey/overview-style titles are slightly
    penalised: they describe ideas well but are rarely the antecedent source
    the tool is looking for.
    """
    for cand in candidates:
        embed = cand.scores.embed or 0.0
        llm = cand.scores.llm
        score = W_EMBED * embed + W_LLM * llm if llm is not None else embed
        if use_year_prior and cand.paper.year:
            ref = before_year or 2026
            if cand.paper.year <= ref:
                # 0 for papers at the reference year, up to W_YEAR for 20+ years older
                age = min(ref - cand.paper.year, 20) / 20
                cand.scores.year_prior = W_YEAR * age
                score += cand.scores.year_prior
        if cand.scores.cite_freq:
            score += cand.scores.cite_freq
        if _SURVEY_TITLE.search(cand.paper.title):
            cand.scores.survey_penalty = W_SURVEY
            score -= W_SURVEY
        cand.scores.final = score
    candidates.sort(key=lambda c: -c.scores.final)
    for i, cand in enumerate(candidates):
        cand.rank = i + 1
    return candidates


async def run_metadata_pipeline(
    conn: Connection,
    claim: str,
    *,
    emit: EmitFn = _noop_emit,
    llm=None,
    context: str | None = None,
    keep: int | None = None,
) -> tuple[list[str], list[Candidate]]:
    """Stages 1-4: queries -> multi-source search -> dedup -> embedding rank.

    Returns (queries_used, candidates). Full-text evidence and LLM judging
    are layered on by the caller (see engine.run_full_pipeline).
    """
    settings = get_settings()
    keep = keep or settings.first_pass_keep

    await emit(StageEvent(stage="query_gen", detail="Generating search queries"))
    queries = fallback_queries(claim)
    if llm is not None:
        try:
            from .query_gen import generate_queries

            plan = await generate_queries(claim, context, llm)
            queries = plan.queries
        except Exception as exc:
            logger.warning("query generation failed, using fallback: %s", exc)
    await emit(StageEvent(stage="query_gen", detail=f"{len(queries)} queries", payload={"queries": queries}))

    async with httpx.AsyncClient(follow_redirects=True) as client:
        metas = await search_sources(client, queries, emit)

        await emit(StageEvent(stage="dedup", detail=f"{len(metas)} raw results"))
        unique = dedupe(metas)
        await emit(StageEvent(stage="dedup", detail=f"{len(unique)} unique papers"))

        await emit(StageEvent(stage="first_pass", detail=f"Embedding {len(unique)} papers"))
        candidates = await first_pass_rank(conn, claim, unique, keep)
        await emit(StageEvent(stage="first_pass", detail=f"Kept top {len(candidates)}"))

        if settings.citation_expansion and candidates:
            from .citations import SeedCitationIndex, expand_with_references

            seeds = [c.paper for c in candidates[: settings.citation_seeds]]
            await emit(
                StageEvent(
                    stage="citations",
                    detail=f"Mining references of top {len(seeds)} candidates",
                )
            )
            try:
                refs, freq = await expand_with_references(client, seeds, emit=emit)
            except Exception as exc:
                logger.warning("citation expansion failed: %s", exc)
                refs, freq = [], {}
            if refs:
                combined = dedupe(unique + refs)
                await emit(
                    StageEvent(
                        stage="citations",
                        detail=f"+{len(refs)} referenced papers ({len(combined)} total), re-ranking",
                    )
                )
                candidates = await first_pass_rank(
                    conn, claim, combined, keep, cite_index=SeedCitationIndex(refs, freq)
                )

    return queries, candidates
