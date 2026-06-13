"""Parse LaTeXML HTML (arxiv.org/html and ar5iv share this format).

Produces reader_html — sanitized HTML where every paragraph carries a
data-p="<n>" anchor — plus plain text for chunking. Selection anchoring
in the frontend and chunk para_start/para_end both key on data-p.
"""

from __future__ import annotations

import html as html_mod
import re

from selectolax.parser import HTMLParser, Node

from ..models import ParsedDoc

_SKIP_SECTIONS = re.compile(
    r"\b(references|bibliography|acknowledg)", re.IGNORECASE
)


def _node_text(node: Node) -> str:
    """Text content with math replaced by its LaTeX alttext."""
    for math in node.css("math"):
        alt = math.attributes.get("alttext") or ""
        math.replace_with(f" {alt} " if alt else " ")
    text = node.text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)


def parse_latexml_html(raw_html: str, fmt: str = "arxiv_html") -> ParsedDoc:
    tree = HTMLParser(raw_html)

    title_node = tree.css_first(".ltx_title_document") or tree.css_first("h1")
    title = _node_text(title_node) if title_node else None

    article = tree.css_first("article") or tree.css_first(".ltx_document") or tree.body
    if article is None:
        raise ValueError("no document body found")

    out_parts: list[str] = []
    plain_parts: list[str] = []
    sections: list[str] = []
    para_idx = 0
    current_section = ""
    skipping = False

    # selectolax css() with a comma selector groups results per selector
    # instead of document order, so walk the tree manually.
    def classes(n: Node) -> set[str]:
        return set(((n.attributes.get("class") or "") if n.attributes else "").split())

    def is_para(n: Node) -> bool:
        cls = classes(n)
        # .ltx_para is the usual block; abstracts use a bare <p class="ltx_p">
        return "ltx_para" in cls or (n.tag == "p" and "ltx_p" in cls)

    matched: list[Node] = []
    for node in article.traverse(include_text=False):
        tag = node.tag or ""
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") or is_para(node):
            matched.append(node)

    for node in matched:
        tag = node.tag
        if tag and tag.startswith("h"):
            heading = _node_text(node)
            if not heading:
                continue
            skipping = bool(_SKIP_SECTIONS.search(heading))
            current_section = heading
            if not skipping:
                sections.append(heading)
                level = min(int(tag[1]) + 0, 6)
                out_parts.append(
                    f"<h{level}>{html_mod.escape(heading)}</h{level}>"
                )
            continue

        if skipping:
            continue
        # skip paragraphs nested inside another matched paragraph block
        parent = node.parent
        nested = False
        while parent is not None:
            if is_para(parent):
                nested = True
                break
            parent = parent.parent
        if nested:
            continue

        text = _node_text(node)
        if not text or len(text) < 3:
            continue
        out_parts.append(
            f'<p data-p="{para_idx}" data-section="{html_mod.escape(current_section)}">'
            f"{html_mod.escape(text)}</p>"
        )
        plain_parts.append(text)
        para_idx += 1

    if not plain_parts:
        raise ValueError("no paragraphs extracted")

    return ParsedDoc(
        title=title,
        reader_html="\n".join(out_parts),
        plain_text="\n\n".join(plain_parts),
        sections=sections,
        format=fmt,
    )
