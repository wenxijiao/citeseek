"""Paragraph-based chunking with section context and reader anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import ParsedDoc

TARGET_TOKENS = 250
OVERLAP_PARAS = 1


@dataclass
class Chunk:
    ord: int
    section: str
    para_start: int
    para_end: int
    text: str


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def chunk_document(doc: ParsedDoc) -> list[Chunk]:
    """Merge data-p paragraphs into ~TARGET_TOKENS chunks with 1-para overlap."""
    paras: list[tuple[int, str, str]] = []  # (para_idx, section, text)
    for match in re.finditer(
        r'<p data-p="(\d+)" data-section="([^"]*)">(.*?)</p>', doc.reader_html, re.DOTALL
    ):
        idx, section, body = int(match.group(1)), match.group(2), match.group(3)
        text = re.sub(r"<[^>]+>", "", body)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            paras.append((idx, section, _unescape(text)))

    chunks: list[Chunk] = []
    i = 0
    while i < len(paras):
        j = i
        tokens = 0
        while j < len(paras) and (tokens == 0 or tokens + _approx_tokens(paras[j][2]) <= TARGET_TOKENS):
            tokens += _approx_tokens(paras[j][2])
            j += 1
        section = paras[i][1]
        body = " ".join(p[2] for p in paras[i:j])
        text = f"§ {section} — {body}" if section else body
        chunks.append(
            Chunk(
                ord=len(chunks),
                section=section,
                para_start=paras[i][0],
                para_end=paras[j - 1][0],
                text=text,
            )
        )
        i = max(j - OVERLAP_PARAS, i + 1)
        if i >= len(paras) or j >= len(paras):
            break
    return chunks


def _unescape(text: str) -> str:
    import html

    return html.unescape(text)
