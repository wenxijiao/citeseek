"""Developer/eval CLI. The web UI and MCP server are the user-facing entries."""

from __future__ import annotations

import argparse
import asyncio
import logging

from rich.console import Console
from rich.table import Table

from .config import get_settings
from .db import connect
from .models import StageEvent

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citeseek", description="Citation evidence workbench")
    parser.add_argument("--provider", help="LLM provider (anthropic|openai|gemini|deepseek|ollama)")
    parser.add_argument("--model", help="LLM model id override")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Metadata search + first-pass ranking for a claim")
    p_search.add_argument("claim")
    p_search.add_argument("--keep", type=int, default=15, help="Candidates to show")
    p_search.add_argument("--no-llm", action="store_true", help="Skip LLM query generation/judging")

    p_run = sub.add_parser("run", help="Full pipeline: search + fulltext evidence + judge")
    p_run.add_argument("claim")
    p_run.add_argument("--keep", type=int, default=10, help="Candidates to return")
    p_run.add_argument("--no-llm", action="store_true")
    p_run.add_argument("--fulltext-top", type=int, default=5)

    p_translate = sub.add_parser("translate", help="Translate a text snippet")
    p_translate.add_argument("text")
    p_translate.add_argument("--lang", default="Chinese", help="Target language")

    p_query = sub.add_parser("query", help="Run a query inside a persistent session")
    p_query.add_argument("claim")
    p_query.add_argument("--session", help="Session id (created if omitted)")
    p_query.add_argument("--parent", help="Parent node id")
    p_query.add_argument("--no-llm", action="store_true")

    sub.add_parser("sessions", help="List sessions")

    p_tree = sub.add_parser("tree", help="Show a session's exploration tree")
    p_tree.add_argument("session")

    p_export = sub.add_parser("export", help="Export a session as a Markdown report")
    p_export.add_argument("session")

    return parser


def _get_llm(args) -> object | None:
    if getattr(args, "no_llm", False):
        return None
    try:
        from .llm.registry import get_llm

        return get_llm(provider=args.provider, model=args.model)
    except Exception as exc:
        console.print(f"[yellow]LLM unavailable ({exc}); using fallback heuristics[/yellow]")
        return None


async def _emit_console(event: StageEvent) -> None:
    console.print(f"[dim]{event.stage}[/dim] {event.detail or ''}")


async def cmd_search(args) -> int:
    from .pipeline.rank import run_metadata_pipeline

    conn = connect(get_settings().db_path)
    llm = _get_llm(args)
    queries, candidates = await run_metadata_pipeline(
        conn, args.claim, emit=_emit_console, llm=llm, keep=args.keep
    )

    if llm is not None and candidates:
        from .pipeline.judge import judge_candidates
        from .pipeline.rank import finalize_scores

        console.print("[dim]judge[/dim] Scoring candidates with LLM")
        candidates = await judge_candidates(args.claim, candidates, llm)
        candidates = finalize_scores(candidates)

    console.print(f"\n[bold]Queries:[/bold] {queries}\n")
    table = Table(title=f"Candidates for: {args.claim!r}")
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Conf", justify="right")
    table.add_column("Verdict")
    table.add_column("Year", justify="right")
    table.add_column("Title", max_width=55)
    table.add_column("ID")
    for cand in candidates:
        table.add_row(
            str(cand.rank),
            f"{cand.scores.final:.3f}",
            f"{cand.confidence:.2f}" if cand.confidence is not None else "-",
            cand.verdict or "-",
            str(cand.paper.year or "?"),
            cand.paper.title,
            cand.paper.arxiv_id or cand.paper.doi or "",
        )
    console.print(table)
    for cand in candidates[:5]:
        if cand.rationale:
            console.print(f"[bold]{cand.rank}.[/bold] {cand.rationale}")
    return 0


async def cmd_run(args) -> int:
    from .pipeline.evidence import attach_evidence
    from .pipeline.judge import judge_candidates
    from .pipeline.rank import finalize_scores, run_metadata_pipeline

    conn = connect(get_settings().db_path)
    llm = _get_llm(args)
    queries, candidates = await run_metadata_pipeline(
        conn, args.claim, emit=_emit_console, llm=llm, keep=max(args.keep * 3, 30)
    )
    candidates = await attach_evidence(
        conn, args.claim, candidates, emit=_emit_console, top_n=args.fulltext_top
    )
    if llm is not None and candidates:
        console.print("[dim]judge[/dim] Scoring candidates with LLM")
        candidates = await judge_candidates(args.claim, candidates, llm)
    candidates = finalize_scores(candidates)[: args.keep]

    console.print(f"\n[bold]Queries:[/bold] {queries}\n")
    for cand in candidates:
        paper = cand.paper
        conf = f" conf={cand.confidence:.2f} ({cand.verdict})" if cand.confidence is not None else ""
        console.print(
            f"[bold]{cand.rank}. {paper.title}[/bold] ({paper.year or '?'}) "
            f"score={cand.scores.final:.3f}{conf}"
        )
        console.print(f"   {paper.url or ''}  [{', '.join(paper.sources)}]")
        if cand.rationale:
            console.print(f"   [italic]{cand.rationale}[/italic]")
        for passage in cand.passages:
            quote = passage.quote[:300] + ("…" if len(passage.quote) > 300 else "")
            console.print(f"   [dim]» ({passage.section or 'body'}, {passage.score:.2f})[/dim] {quote}")
        console.print()
    return 0


async def cmd_translate(args) -> int:
    from .translate import translate_snippet

    llm = _get_llm(args)
    if llm is None:
        console.print("[red]Translation requires an LLM provider/API key[/red]")
        return 1
    console.print(await translate_snippet(args.text, args.lang, llm))
    return 0


async def cmd_query(args) -> int:
    from .engine import get_engine

    engine = get_engine()
    if args.session:
        session_id = args.session
    else:
        session = engine.create_session(title=args.claim[:60])
        session_id = session.id
        console.print(f"[dim]session[/dim] {session_id}")

    node_id = engine.start_query(session_id, args.claim, parent_node_id=args.parent)
    queue = engine.subscribe(node_id)
    while True:
        event = await queue.get()
        console.print(f"[dim]{event.stage}[/dim] {event.detail or ''}")
        if event.stage in ("done", "error"):
            break
    node = engine.get_node(node_id)
    if node:
        for cand in node.candidates[:10]:
            conf = f" conf={cand.confidence:.2f}" if cand.confidence is not None else ""
            console.print(
                f"{cand.rank}. {cand.paper.title} ({cand.paper.year or '?'}) "
                f"score={cand.scores.final:.3f}{conf}"
            )
    console.print(f"\nnode: {node_id}")
    return 0


async def cmd_sessions(args) -> int:
    from .engine import get_engine

    for session in get_engine().list_sessions():
        console.print(
            f"{session.id}  [{session.node_count} nodes]  {session.title or ''}  ({session.updated_at})"
        )
    return 0


async def cmd_tree(args) -> int:
    from .engine import get_engine

    nodes = get_engine().get_tree(args.session)
    by_parent: dict = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    def walk(parent_id, depth):
        for node in by_parent.get(parent_id, []):
            unread = f" ({node.unread_count} unread)" if node.unread_count else ""
            console.print(
                f"{'  ' * depth}• [{node.status}] {node.selected_text[:70]} "
                f"[dim]{node.candidate_count} candidates{unread} — {node.id[:8]}[/dim]"
            )
            walk(node.id, depth + 1)

    walk(None, 0)
    return 0


async def cmd_export(args) -> int:
    from .engine import get_engine

    print(get_engine().export_report(args.session))
    return 0


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    commands = {
        "search": cmd_search,
        "run": cmd_run,
        "translate": cmd_translate,
        "query": cmd_query,
        "sessions": cmd_sessions,
        "tree": cmd_tree,
        "export": cmd_export,
    }
    raise SystemExit(asyncio.run(commands[args.command](args)))


if __name__ == "__main__":
    main()
