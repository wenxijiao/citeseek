"""MCP server (stdio) — exposes the citation workbench to MCP clients.

stdout belongs to the MCP protocol; all logging goes to stderr and HF
progress bars are disabled (see pipeline.embeddings). Tools return
Markdown strings, await pipeline completion, and report progress via ctx.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import Context, FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

mcp = FastMCP(
    "citeseek",
    instructions=(
        "CiteSeek finds supporting/antecedent papers with passage-level "
        "evidence and confidence scores for research claims. Typical flow: "
        "find_supporting_papers(claim) -> open_paper(ref) -> select a new "
        "claim from the text -> find_supporting_papers(claim, session_id, "
        "parent_node_id) again. Use show_exploration_tree to navigate and "
        "export_report for a final evidence-chain report."
    ),
)


def _engine():
    from .engine import get_engine

    return get_engine()


def _format_candidates(node) -> str:
    lines = [
        f"## Candidates for: “{node.selected_text}”",
        f"(node `{node.id}`, session `{node.session_id}`)",
        "",
    ]
    for cand in node.candidates[:15]:
        paper = cand.paper
        conf = f" — confidence **{cand.confidence:.2f}** ({cand.verdict})" if cand.confidence is not None else ""
        ref = paper.arxiv_id or paper.doi or str(cand.paper_id)
        lines.append(
            f"{cand.rank}. **{paper.title}** ({paper.year or '?'}){conf}  "
        )
        lines.append(f"   ref: `{ref}` | paper_id: {cand.paper_id} | {paper.url or 'no url'}  ")
        if cand.rationale:
            lines.append(f"   {cand.rationale}  ")
        for passage in cand.passages[:2]:
            lines.append(f"   > {passage.quote[:350]}  ")
        lines.append("")
    return "\n".join(lines)


def _resolve_paper_id(ref: str) -> int | None:
    """Accept a paper_id, arXiv id, or DOI."""
    conn = _engine().conn
    if ref.isdigit():
        row = conn.execute("SELECT id FROM papers WHERE id = ?", (int(ref),)).fetchone()
        if row:
            return row["id"]
    row = conn.execute(
        "SELECT id FROM papers WHERE arxiv_id = ? OR doi = ?", (ref, ref.lower())
    ).fetchone()
    return row["id"] if row else None


@mcp.tool()
async def find_supporting_papers(
    claim: str,
    session_id: str = "",
    parent_node_id: str = "",
    paper_ref: str = "",
    ctx: Context = None,
) -> str:
    """Find papers that support or are plausible earlier sources for a claim.

    Args:
        claim: The sentence/claim to find supporting evidence for.
        session_id: Existing session to add this query to (omit to create one).
        parent_node_id: Node this claim was selected from (for recursive reading).
        paper_ref: arXiv id/DOI/paper_id of the paper the claim was selected in.
    """
    engine = _engine()
    if not session_id:
        session = engine.create_session(title=claim[:60])
        session_id = session.id
    paper_id = _resolve_paper_id(paper_ref) if paper_ref else None

    node_id = engine.start_query(
        session_id, claim, parent_node_id=parent_node_id or None, paper_id=paper_id
    )
    queue = engine.subscribe(node_id)
    try:
        while True:
            event = await queue.get()
            if ctx is not None:
                await ctx.report_progress(0, None, f"{event.stage}: {event.detail or ''}")
            if event.stage in ("done", "error"):
                break
    finally:
        engine.unsubscribe(node_id, queue)

    node = engine.get_node(node_id)
    if node is None or node.status == "error":
        return f"Pipeline failed: {node.error if node else 'unknown node'}"
    return _format_candidates(node)


@mcp.tool()
async def open_paper(paper_ref: str) -> str:
    """Open a paper's full text (fetching it if needed). paper_ref accepts an
    arXiv id, DOI, or numeric paper_id. Marks related candidates as read."""
    import httpx

    from .pipeline.evidence import ensure_fulltext

    engine = _engine()
    paper_id = _resolve_paper_id(paper_ref)
    if paper_id is None:
        return f"Unknown paper: {paper_ref}"
    conn = engine.conn
    conn.execute(
        "UPDATE candidates SET read_status = 'opened' WHERE paper_id = ? AND read_status = 'unread'",
        (paper_id,),
    )
    conn.commit()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        ok = await ensure_fulltext(conn, client, paper_id)
    paper, doc = engine.get_document(paper_id)
    header = f"# {paper.title}\n*{', '.join(paper.authors[:6])} ({paper.year or '?'})* — {paper.url or ''}\n\n"
    if not ok or doc is None:
        abstract = paper.abstract or "No abstract available."
        return header + f"Full text unavailable (paywalled or no arXiv version).\n\nAbstract: {abstract}"
    text = doc["plain_text"]
    if len(text) > 60000:
        text = text[:60000] + "\n\n[truncated — use get_paper_passages to search the rest]"
    return header + text


@mcp.tool()
async def get_paper_passages(paper_ref: str, query: str, k: int = 5) -> str:
    """Retrieve the k passages of a (fetched) paper most relevant to a query."""
    engine = _engine()
    paper_id = _resolve_paper_id(paper_ref)
    if paper_id is None:
        return f"Unknown paper: {paper_ref}"
    passages = engine.get_passages(paper_id, query, k)
    if not passages:
        return "No indexed passages (paper may not have full text). Try open_paper first."
    return "\n\n".join(
        f"**[{p.section or 'body'}]** (score {p.score:.2f})\n{p.quote}" for p in passages
    )


@mcp.tool()
async def show_exploration_tree(session_id: str) -> str:
    """Show the exploration tree of a session: every claim queried, candidate
    counts, and unread counts. Use go_to_node to revisit any node."""
    nodes = _engine().get_tree(session_id)
    if not nodes:
        return "Empty session."
    by_parent: dict = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)
    lines: list[str] = []

    def walk(parent_id, depth):
        for node in by_parent.get(parent_id, []):
            unread = f", {node.unread_count} unread" if node.unread_count else ""
            lines.append(
                f"{'  ' * depth}- [{node.status}] “{node.selected_text[:80]}” "
                f"({node.candidate_count} candidates{unread}) — node `{node.id}`"
            )
            walk(node.id, depth + 1)

    walk(None, 0)
    return "\n".join(lines)


@mcp.tool()
async def go_to_node(node_id: str) -> str:
    """Revisit a node in the exploration tree: shows its full ranked candidate
    list including the ones not yet read."""
    node = _engine().get_node(node_id)
    if node is None:
        return f"Unknown node: {node_id}"
    return _format_candidates(node)


@mcp.tool()
async def list_sessions() -> str:
    """List existing CiteSeek sessions."""
    sessions = _engine().list_sessions()
    if not sessions:
        return "No sessions yet."
    return "\n".join(
        f"- `{s.id}` — {s.title or 'untitled'} ({s.node_count} nodes, updated {s.updated_at})"
        for s in sessions
    )


@mcp.tool()
async def translate(text: str, target_lang: str = "") -> str:
    """Translate a snippet (keeps technical terms in the original language).
    target_lang defaults to the configured language (Chinese unless changed)."""
    try:
        return await _engine().translate(text, target_lang or None)
    except RuntimeError as exc:
        return str(exc)


@mcp.tool()
async def export_report(session_id: str) -> str:
    """Export a session's exploration tree as a Markdown evidence-chain report."""
    try:
        return _engine().export_report(session_id)
    except ValueError as exc:
        return str(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
