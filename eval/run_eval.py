"""Evaluation harness: compare ranking configurations on the benchmark.

For each benchmark claim we retrieve candidates once (cached to
eval/cache/ so reruns are offline and deterministic), then rank with
each configuration and score against the gold antecedent papers.

Metrics:
- Recall@k  — |gold ∩ top-k| / |gold|, averaged over claims
- Hit@k     — fraction of claims with at least one gold paper in top-k
- MRR       — mean reciprocal rank of the first gold paper

Usage:
    .venv/bin/python eval/run_eval.py                 # lexical/embed/embed+year
    .venv/bin/python eval/run_eval.py --llm           # adds the LLM-judge config
    .venv/bin/python eval/run_eval.py --out eval/results.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citeseek.models import Candidate, CandidateScores, PaperMeta, StageEvent  # noqa: E402
from citeseek.pipeline.dedup import dedupe  # noqa: E402
from citeseek.pipeline.embeddings import get_embedder  # noqa: E402
from citeseek.pipeline.rank import fallback_queries, search_sources  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CACHE_DIR = EVAL_DIR / "cache"
KS = (5, 10, 20)


async def _quiet_emit(event: StageEvent) -> None:
    return None


def _speed_up_s2_failures() -> None:
    """Unauthenticated Semantic Scholar 429s constantly; fail fast in eval runs
    instead of spending ~20s of exponential backoff per query."""
    import functools

    from citeseek.sources import semantic_scholar
    from citeseek.sources.ratelimit import polite_get

    semantic_scholar.polite_get = functools.partial(polite_get, max_retries=1)


async def gather_candidates(item: dict, llm=None, want_llmq: bool = False) -> list[PaperMeta]:
    """Multi-source metadata retrieval with on-disk caching.

    With an LLM, queries come from query generation (the full system);
    without, from the stopword-stripping fallback. Cached separately.
    ``want_llmq`` reads the llmq cache without an LLM (offline reruns).
    """
    suffix = "-llmq" if (llm or want_llmq) else ""
    cache_file = CACHE_DIR / f"{item['id']}{suffix}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        return [PaperMeta.model_validate(m) for m in data]
    if llm:
        from citeseek.pipeline.query_gen import generate_queries

        try:
            queries = (await generate_queries(item["claim"], None, llm)).queries
        except Exception:
            queries = fallback_queries(item["claim"])
    else:
        queries = fallback_queries(item["claim"])
    async with httpx.AsyncClient(follow_redirects=True) as client:
        metas = await search_sources(client, queries, _quiet_emit, limit=25)
    unique = dedupe(metas)
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps([m.model_dump() for m in unique]))
    return unique


def _is_gold(meta: PaperMeta, gold: list[str]) -> bool:
    ids = {g.lower() for g in gold}
    # arXiv-assigned DOIs (10.48550/arxiv.X) and version suffixes count as
    # the same paper as a bare arXiv id.
    arxiv = (meta.arxiv_id or "").lower().split("v")[0]
    doi = (meta.doi or "").lower()
    if doi.startswith("10.48550/arxiv."):
        arxiv = arxiv or doi.removeprefix("10.48550/arxiv.")
    gold_arxiv = {g.removeprefix("10.48550/arxiv.") for g in ids}
    return bool((arxiv and arxiv in gold_arxiv) or (doi and doi in ids))


async def gather_cite_candidates(
    item: dict, base: list[PaperMeta], top_k: int = 10
) -> tuple[list[PaperMeta], dict[str, int]]:
    """Backward snowballing on top of the llmq candidates, cached on disk."""
    from citeseek.pipeline.citations import expand_with_references

    cache_file = CACHE_DIR / f"{item['id']}-cite.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        return [PaperMeta.model_validate(m) for m in data["refs"]], data["freq"]
    scores = _embed_scores(item["claim"], base)
    seeds = [base[i] for i in np.argsort(-scores)[:top_k]]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        refs, freq = await expand_with_references(client, seeds)
    cache_file.write_text(
        json.dumps({"refs": [m.model_dump() for m in refs], "freq": freq})
    )
    return refs, freq


# ---- ranking configurations ---------------------------------------------------


def rank_bm25(claim: str, metas: list[PaperMeta]) -> list[PaperMeta]:
    from rank_bm25 import BM25Okapi

    docs = [f"{m.title} {m.abstract or ''}".lower().split() for m in metas]
    bm25 = BM25Okapi(docs)
    scores = bm25.get_scores(claim.lower().split())
    order = np.argsort(-scores)
    return [metas[i] for i in order]


def _embed_scores(claim: str, metas: list[PaperMeta]) -> np.ndarray:
    embedder = get_embedder()
    qvec = embedder.embed_query(claim)
    texts = [f"{m.title}. {m.abstract or ''}".strip() for m in metas]
    vecs = embedder.embed_passages(texts)
    return vecs @ qvec


def rank_embed(claim: str, metas: list[PaperMeta]) -> list[PaperMeta]:
    scores = _embed_scores(claim, metas)
    return [metas[i] for i in np.argsort(-scores)]


def _freq_bonus(metas: list[PaperMeta], index, top_k: int = 10) -> np.ndarray:
    """Seed-citation frequency (fuzzy-title aggregated) as a signal in [0, 1]."""
    return np.array([min(index.count_for(m), top_k) / top_k for m in metas])


def rank_embed_freq(claim: str, metas: list[PaperMeta], index) -> list[PaperMeta]:
    scores = _embed_scores(claim, metas) + 0.3 * _freq_bonus(metas, index)
    return [metas[i] for i in np.argsort(-scores)]


def rank_embed_year(claim: str, metas: list[PaperMeta]) -> list[PaperMeta]:
    scores = _embed_scores(claim, metas)
    years = np.array([m.year or 2026 for m in metas], dtype=float)
    age = np.clip(2026 - years, 0, 20) / 20
    return [metas[i] for i in np.argsort(-(scores + 0.05 * age))]


async def rank_embed_llm(
    claim: str, metas: list[PaperMeta], llm, index=None
) -> list[PaperMeta]:
    """Embedding (+seed-citation frequency) shortlist (top 30) -> LLM judge."""
    from citeseek.pipeline.judge import judge_candidates
    from citeseek.pipeline.rank import finalize_scores

    embed_scores = _embed_scores(claim, metas)
    bonus = 0.3 * _freq_bonus(metas, index) if index else np.zeros(len(metas))
    scores = embed_scores + bonus
    order = np.argsort(-scores)[:30]
    candidates = [
        Candidate(
            rank=i + 1,
            paper_id=i,
            paper=metas[idx],
            scores=CandidateScores(
                embed=float(embed_scores[idx]),
                cite_freq=float(bonus[idx]) or None,
                final=float(scores[idx]),
            ),
        )
        for i, idx in enumerate(order)
    ]
    candidates = await judge_candidates(claim, candidates, llm)
    candidates = finalize_scores(candidates, use_year_prior=True)
    ranked = [c.paper for c in candidates]
    ranked += [metas[i] for i in np.argsort(-scores)[30:]]
    return ranked


# ---- metrics ----------------------------------------------------------------


def score_ranking(ranked: list[PaperMeta], gold: list[str]) -> dict:
    hits = [i for i, m in enumerate(ranked) if _is_gold(m, gold)]
    n_gold_found_total = len(hits)
    result = {}
    for k in KS:
        in_k = sum(1 for i in hits if i < k)
        denom = min(len(gold), len(ranked)) or 1
        result[f"recall@{k}"] = in_k / denom
        result[f"hit@{k}"] = 1.0 if in_k > 0 else 0.0
    result["mrr"] = 1.0 / (hits[0] + 1) if hits else 0.0
    result["gold_retrieved"] = n_gold_found_total
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="Include the LLM-judge config")
    parser.add_argument("--cite", action="store_true", help="Include citation-expansion configs")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default=str(EVAL_DIR / "results.md"))
    args = parser.parse_args()

    _speed_up_s2_failures()
    items = [
        json.loads(line)
        for line in (EVAL_DIR / "benchmark.jsonl").read_text().splitlines()
        if line.strip()
    ]

    llm = None
    if args.llm:
        from citeseek.llm.registry import get_llm

        llm = get_llm(provider=args.provider, model=args.model)
        print(f"LLM judge: {llm.provider}/{llm.model}")

    configs = ["bm25", "embed", "embed+year"] + (
        ["embed+llm", "llmq+embed", "llmq+embed+llm (full)"] if llm else []
    )
    if args.cite:
        configs += ["llmq+cite+embed", "llmq+cite+embed+freq"]
        if llm:
            configs += ["llmq+cite+embed+freq+llm (full+cite)"]
    per_config: dict[str, list[dict]] = {c: [] for c in configs}
    retrievable = 0
    retrievable_llmq = 0
    retrievable_cite = 0

    for item in items:
        metas = await gather_candidates(item)
        gold_present = sum(1 for m in metas if _is_gold(m, item["gold"]))
        if gold_present:
            retrievable += 1
        line = (
            f"[{item['id']:>12}] {len(metas):>3} candidates, "
            f"{gold_present}/{len(item['gold'])} gold retrievable"
        )
        per_config["bm25"].append(score_ranking(rank_bm25(item["claim"], metas), item["gold"]))
        per_config["embed"].append(score_ranking(rank_embed(item["claim"], metas), item["gold"]))
        per_config["embed+year"].append(
            score_ranking(rank_embed_year(item["claim"], metas), item["gold"])
        )
        metas_llmq: list[PaperMeta] = []
        if llm:
            ranked = await rank_embed_llm(item["claim"], metas, llm)
            per_config["embed+llm"].append(score_ranking(ranked, item["gold"]))

            metas_llmq = await gather_candidates(item, llm)
            gold_llmq = sum(1 for m in metas_llmq if _is_gold(m, item["gold"]))
            if gold_llmq:
                retrievable_llmq += 1
            line += f" | llm-queries: {len(metas_llmq):>3} candidates, {gold_llmq}/{len(item['gold'])} gold"
            per_config["llmq+embed"].append(
                score_ranking(rank_embed(item["claim"], metas_llmq), item["gold"])
            )
            ranked_full = await rank_embed_llm(item["claim"], metas_llmq, llm)
            per_config["llmq+embed+llm (full)"].append(score_ranking(ranked_full, item["gold"]))

        if args.cite:
            if not metas_llmq:
                metas_llmq = await gather_candidates(item, llm, want_llmq=True)
            if metas_llmq:
                refs, freq = await gather_cite_candidates(item, metas_llmq)
                combined = dedupe(metas_llmq + refs)
            else:
                refs, freq, combined = [], {}, []
            from citeseek.pipeline.citations import SeedCitationIndex

            cite_index = SeedCitationIndex(refs, freq)
            gold_cite = sum(1 for m in combined if _is_gold(m, item["gold"]))
            if gold_cite:
                retrievable_cite += 1
            line += f" | +cite: {len(combined):>3} candidates, {gold_cite}/{len(item['gold'])} gold"
            if combined:
                per_config["llmq+cite+embed"].append(
                    score_ranking(rank_embed(item["claim"], combined), item["gold"])
                )
                per_config["llmq+cite+embed+freq"].append(
                    score_ranking(
                        rank_embed_freq(item["claim"], combined, cite_index), item["gold"]
                    )
                )
                if llm:
                    ranked_cite = await rank_embed_llm(item["claim"], combined, llm, cite_index)
                    per_config["llmq+cite+embed+freq+llm (full+cite)"].append(
                        score_ranking(ranked_cite, item["gold"])
                    )
            else:
                zero = score_ranking([], item["gold"])
                per_config["llmq+cite+embed"].append(zero)
                per_config["llmq+cite+embed+freq"].append(zero)
                if llm:
                    per_config["llmq+cite+embed+freq+llm (full+cite)"].append(zero)
        print(line, flush=True)

    # ---- report ----
    ceiling = (
        f"{retrievable}/{len(items)} claims with fallback queries"
        + (f", {retrievable_llmq}/{len(items)} with LLM query generation" if llm else "")
        + (f", {retrievable_cite}/{len(items)} with citation expansion" if args.cite else "")
    )
    judge_desc = f"{llm.provider}/{llm.model}" if llm else "none"
    lines = [
        "# CiteSeek ranking evaluation",
        "",
        f"Judge: {judge_desc} | citation expansion: {'on' if args.cite else 'off'} | "
        f"generated by run_eval.py",
        "",
        f"{len(items)} claims; gold papers retrievable by metadata search for {ceiling} "
        "(retrieval ceiling).",
        "",
        "| config | " + " | ".join(f"R@{k}" for k in KS) + " | " + " | ".join(f"Hit@{k}" for k in KS) + " | MRR |",
        "|---|" + "---|" * (2 * len(KS) + 1),
    ]
    for config in configs:
        rows = per_config[config]
        avg = lambda key: sum(r[key] for r in rows) / len(rows)  # noqa: E731
        lines.append(
            f"| {config} | "
            + " | ".join(f"{avg(f'recall@{k}'):.3f}" for k in KS)
            + " | "
            + " | ".join(f"{avg(f'hit@{k}'):.3f}" for k in KS)
            + f" | {avg('mrr'):.3f} |"
        )
    report = "\n".join(lines)
    Path(args.out).write_text(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    asyncio.run(main())
