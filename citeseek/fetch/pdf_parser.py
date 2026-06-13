"""PDF fallback parsing via pymupdf. Lower fidelity than the HTML path."""

from __future__ import annotations

import html as html_mod
import re

from ..models import ParsedDoc

_SKIP_AFTER = re.compile(r"^\s*(references|bibliography|acknowledg\w*)\s*$", re.IGNORECASE)


def _title_from_layout(doc) -> str | None:
    """Largest-font line(s) near the top of page 1 — most PDFs lack metadata."""
    try:
        page = doc[0]
        spans = [
            (span["size"], span["text"].strip())
            for block in page.get_text("dict")["blocks"]
            if block.get("type") == 0
            for line in block["lines"]
            # horizontal text only — skips arXiv's rotated sidebar watermark
            if abs(line["dir"][0]) > 0.99
            for span in line["spans"]
            if span["text"].strip() and not span["text"].strip().lower().startswith("arxiv:")
        ]
        if not spans:
            return None
        max_size = max(s for s, _ in spans)
        parts = [t for s, t in spans if s >= max_size - 0.5]
        title = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return title if 8 <= len(title) <= 300 else None
    except Exception:
        return None


def parse_pdf(data: bytes) -> ParsedDoc:
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    paragraphs: list[str] = []
    title = doc.metadata.get("title") or _title_from_layout(doc)

    stop = False
    for page in doc:
        if stop:
            break
        for block in page.get_text("blocks"):
            text = re.sub(r"\s+", " ", block[4]).strip()
            if not text or len(text) < 30:
                continue
            if _SKIP_AFTER.match(text):
                stop = True
                break
            # de-hyphenate line-break splits
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)
            paragraphs.append(text)
    doc.close()

    if not paragraphs:
        raise ValueError("no text extracted from PDF")

    reader_html = "\n".join(
        f'<p data-p="{i}" data-section="">{html_mod.escape(p)}</p>'
        for i, p in enumerate(paragraphs)
    )
    return ParsedDoc(
        title=title,
        reader_html=reader_html,
        plain_text="\n\n".join(paragraphs),
        sections=[],
        format="pdf",
    )
