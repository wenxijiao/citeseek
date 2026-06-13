"""LLM judge: rerank candidate papers against the claim with confidence scores."""

from __future__ import annotations

import asyncio
import logging

from ..llm.base import LLMClient, LLMError
from ..models import Candidate, JudgmentBatch

logger = logging.getLogger(__name__)

SYSTEM = """You judge whether candidate papers support or are plausible earlier \
sources for a research claim. For each candidate, return:
- ref: the candidate's index as given
- verdict: one of supports | partially_supports | background | unrelated
- confidence: 0.0-1.0 — how confident you are that this paper supports or \
originated the idea in the claim (not merely topical similarity)
- rationale: 1-2 sentences explaining the relationship
- best_quote: if evidence passages were provided, the single most relevant \
sentence copied verbatim from them, else null

Favor papers that introduce or substantiate the idea over papers that merely \
use or survey it. Earlier work that originated the idea deserves the highest \
confidence."""

BATCH_SIZE = 10


def _format_candidate(idx: int, cand: Candidate) -> str:
    paper = cand.paper
    lines = [
        f"[{idx}] {paper.title} ({paper.year or 'year?'})",
        f"    Venue: {paper.venue or 'unknown'} | Citations: {paper.citation_count or '?'}",
    ]
    if paper.abstract:
        lines.append(f"    Abstract: {paper.abstract[:900]}")
    for p in cand.passages[:3]:
        lines.append(f"    Evidence ({p.section or 'body'}): {p.quote[:500]}")
    return "\n".join(lines)


async def judge_candidates(
    claim: str, candidates: list[Candidate], llm: LLMClient
) -> list[Candidate]:
    """Attach verdict/confidence/rationale to candidates. Mutates and returns them.

    A failed judge batch degrades to embedding-only scoring for that batch.
    """
    batches = [
        candidates[i : i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)
    ]

    async def judge_batch(batch: list[Candidate]) -> None:
        user = "Claim: " + claim + "\n\nCandidates:\n\n" + "\n\n".join(
            _format_candidate(i, c) for i, c in enumerate(batch)
        )
        try:
            result = await llm.complete_json(SYSTEM, user, JudgmentBatch, max_tokens=4000)
        except LLMError as exc:
            logger.warning("judge batch failed, keeping embedding scores: %s", exc)
            return
        for judgment in result.judgments:
            if 0 <= judgment.ref < len(batch):
                cand = batch[judgment.ref]
                cand.verdict = judgment.verdict
                cand.confidence = judgment.confidence
                cand.rationale = judgment.rationale
                cand.scores.llm = judgment.confidence
                # Evidence-grounding check: the judge's chosen quote only
                # counts if it actually appears in a retrieved passage —
                # the matching passage is then surfaced first. A paraphrased
                # or invented quote is silently ignored.
                if judgment.best_quote and cand.passages:
                    needle = " ".join(judgment.best_quote.split()).lower()
                    for i, p in enumerate(cand.passages):
                        if needle and needle in " ".join(p.quote.split()).lower():
                            cand.passages.insert(0, cand.passages.pop(i))
                            break

    await asyncio.gather(*(judge_batch(b) for b in batches))
    return candidates
