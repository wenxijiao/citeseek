"""Snippet translation that keeps technical terminology legible."""

from __future__ import annotations

from .llm.base import LLMClient

SYSTEM = """You translate excerpts from academic AI papers. Rules:
- Keep technical terms, model names, dataset names, and math in the original \
language, adding the translation in parentheses on first occurrence — e.g. \
"对抗训练（adversarial training）"
- Preserve the academic register; do not summarize or omit content
- Return only the translation, no preamble"""


async def translate_snippet(
    text: str, target_lang: str, llm: LLMClient
) -> str:
    user = f"Translate the following into {target_lang}:\n\n{text}"
    return (await llm.complete(SYSTEM, user, max_tokens=3000)).strip()
