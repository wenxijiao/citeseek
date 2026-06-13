"""Export a session's exploration tree as a Markdown evidence-chain report."""

from __future__ import annotations

from ..db import Connection
from ..models import NodeDetail, NodeSummary
from .store import get_node, get_session, get_tree


def _format_node(conn: Connection, node: NodeDetail, depth: int) -> list[str]:
    indent = "  " * depth
    lines = []
    origin = f" *(selected in: {node.paper_title})*" if node.paper_title else ""
    lines.append(f"{indent}- **Claim:** “{node.selected_text}”{origin}")
    for cand in node.candidates:
        if cand.read_status == "dismissed":
            continue
        paper = cand.paper
        conf = f", confidence {cand.confidence:.2f}" if cand.confidence is not None else ""
        verdict = f" — *{cand.verdict}*" if cand.verdict else ""
        read = " ✓read" if cand.read_status == "opened" else ""
        lines.append(
            f"{indent}  {cand.rank}. **{paper.title}** ({paper.year or '?'}{conf}){verdict}{read}  "
        )
        if paper.url:
            lines.append(f"{indent}     <{paper.url}>  ")
        if cand.rationale:
            lines.append(f"{indent}     {cand.rationale}  ")
        for passage in cand.passages[:2]:
            quote = passage.quote[:400]
            lines.append(f"{indent}     > {quote}  ")
    return lines


def export_report(conn: Connection, session_id: str) -> str:
    session = get_session(conn, session_id)
    if session is None:
        raise ValueError(f"unknown session {session_id}")
    tree = get_tree(conn, session_id)
    by_parent: dict[str | None, list[NodeSummary]] = {}
    for node in tree:
        by_parent.setdefault(node.parent_id, []).append(node)

    lines = [
        f"# Evidence Chain Report — {session.title or session.id[:8]}",
        "",
        f"*Session created {session.created_at}; exported by CiteSeek.*",
        "",
    ]

    def walk(parent_id: str | None, depth: int) -> None:
        for summary in by_parent.get(parent_id, []):
            detail = get_node(conn, summary.id)
            if detail:
                lines.extend(_format_node(conn, detail, depth))
                lines.append("")
            walk(summary.id, depth + 1)

    walk(None, 0)
    return "\n".join(lines)
