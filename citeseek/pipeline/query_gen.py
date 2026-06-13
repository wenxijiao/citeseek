"""LLM-assisted search query generation from a selected claim."""

from __future__ import annotations

from ..llm.base import LLMClient
from ..models import QueryPlan

SYSTEM = """You help researchers find the original sources and antecedents of \
scientific claims in AI research. Given a claim (and optional surrounding \
context from the paper it was selected in), produce keyword search queries for \
scholarly search engines (arXiv, Semantic Scholar, OpenAlex).

Guidelines:
- 3 to 5 queries, each 2-8 keywords, no boolean operators or quotes
- Cover different angles: the technique's canonical name, earlier/alternative \
terminology, and the underlying concept (older papers often use different terms)
- Also list the key technical concepts the claim relies on"""


async def generate_queries(
    claim: str, context: str | None, llm: LLMClient
) -> QueryPlan:
    user = f"Claim: {claim}"
    if context:
        user += f"\n\nSurrounding context from the paper:\n{context[:2000]}"
    return await llm.complete_json(SYSTEM, user, QueryPlan, max_tokens=1500)
