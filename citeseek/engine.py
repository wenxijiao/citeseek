"""The single core service layer.

Both adapters (FastAPI routes and MCP tools) call into Engine; neither
contains business logic. Pipeline runs are asyncio tasks that broadcast
StageEvents to per-node subscriber queues (consumed by SSE and by MCP
progress reporting). State always lands in SQLite first, so a dropped
stream recovers by re-reading the node.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .config import get_settings
from .db import Connection, connect
from .llm.base import LLMClient
from .models import (
    Candidate,
    NodeDetail,
    NodeSummary,
    PaperMeta,
    Passage,
    SelectionAnchor,
    Session,
    StageEvent,
)
from .pipeline.embeddings import get_embedder
from .pipeline.evidence import attach_evidence, ensure_fulltext
from .pipeline.index import VectorIndex
from .pipeline.judge import judge_candidates
from .pipeline.rank import finalize_scores, run_metadata_pipeline
from .session import export as export_mod
from .session import store
from .translate import translate_snippet

logger = logging.getLogger(__name__)

_DONE = StageEvent(stage="done")


class Engine:
    def __init__(self, conn: Connection | None = None) -> None:
        self.conn = conn or connect(get_settings().db_path)
        self._subscribers: dict[str, list[asyncio.Queue[StageEvent]]] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # ---- LLM resolution -------------------------------------------------

    def get_llm(self) -> LLMClient | None:
        """Resolve the active LLM from the settings table (fallback to env)."""
        from .llm.registry import get_llm

        overrides = store.get_settings_map(self.conn)
        try:
            return get_llm(
                provider=overrides.get("llm.provider"),
                model=overrides.get("llm.model"),
            )
        except Exception as exc:
            logger.info("LLM unavailable: %s", exc)
            return None

    # ---- sessions & tree -------------------------------------------------

    def create_session(
        self, title: str | None = None, root_paper_id: int | None = None
    ) -> Session:
        return store.create_session(self.conn, title, root_paper_id)

    def delete_session(self, session_id: str) -> None:
        store.delete_session(self.conn, session_id)

    def upload_pdf(
        self, data: bytes, *, paper_id: int | None = None, title_hint: str | None = None
    ) -> int:
        """Parse an uploaded PDF into a readable, indexed document.

        With paper_id, attaches full text to an existing (paywalled) paper;
        otherwise creates a new user-uploaded paper record. Returns paper_id.
        """
        from .fetch.fulltext import save_document
        from .fetch.pdf_parser import parse_pdf
        from .pipeline.evidence import index_document
        from .pipeline.store import upsert_paper

        doc = parse_pdf(data)
        if paper_id is None:
            title = (title_hint or doc.title or "Uploaded paper").strip()
            paper_id = upsert_paper(self.conn, PaperMeta(title=title, open_access=False))
        save_document(self.conn, paper_id, doc)
        index_document(self.conn, paper_id, doc)
        self.save_pdf(paper_id, data)
        return paper_id

    def list_sessions(self) -> list[Session]:
        return store.list_sessions(self.conn)

    def get_tree(self, session_id: str) -> list[NodeSummary]:
        return store.get_tree(self.conn, session_id)

    def get_node(self, node_id: str) -> NodeDetail | None:
        return store.get_node(self.conn, node_id)

    def rename_session(self, session_id: str, title: str) -> None:
        store.rename_session(self.conn, session_id, title)

    # ---- query pipeline ----------------------------------------------------

    def start_query(
        self,
        session_id: str,
        selected_text: str,
        *,
        parent_node_id: str | None = None,
        paper_id: int | None = None,
        anchor: SelectionAnchor | None = None,
        context_text: str | None = None,
    ) -> str:
        """Create a tree node and launch its pipeline task. Returns node_id."""
        node_id = store.create_node(
            self.conn,
            session_id,
            selected_text,
            parent_id=parent_node_id,
            paper_id=paper_id,
            anchor=anchor,
            context_text=context_text,
        )
        self._tasks[node_id] = asyncio.create_task(self._run_node(node_id))
        return node_id

    async def _emit(self, node_id: str, event: StageEvent) -> None:
        for queue in self._subscribers.get(node_id, []):
            await queue.put(event)

    async def _run_node(self, node_id: str) -> None:
        node = store.get_node(self.conn, node_id)
        if node is None:
            return
        settings = get_settings()
        store.set_node_status(self.conn, node_id, "running")

        async def emit(event: StageEvent) -> None:
            await self._emit(node_id, event)

        try:
            llm = self.get_llm()
            before_year = None
            if node.paper_id:
                row = self.conn.execute(
                    "SELECT year FROM papers WHERE id = ?", (node.paper_id,)
                ).fetchone()
                before_year = row["year"] if row else None

            queries, candidates = await run_metadata_pipeline(
                self.conn, node.selected_text, emit=emit, llm=llm,
                context=node.context_text,
            )
            store.set_node_status(self.conn, node_id, "running", queries=queries)

            candidates = await attach_evidence(
                self.conn, node.selected_text, candidates, emit=emit
            )
            if llm is not None and candidates:
                await emit(StageEvent(stage="judge", detail="Scoring candidates with LLM"))
                candidates = await judge_candidates(node.selected_text, candidates, llm)
            candidates = finalize_scores(candidates, before_year=before_year)
            candidates = candidates[: settings.candidates_returned * 3]

            store.save_candidates(self.conn, node_id, candidates)
            store.set_node_status(self.conn, node_id, "done")
            await emit(
                StageEvent(
                    stage="done",
                    detail=f"{len(candidates)} candidates",
                    payload={"node_id": node_id},
                )
            )
        except Exception as exc:
            logger.exception("pipeline failed for node %s", node_id)
            store.set_node_status(self.conn, node_id, "error", error=str(exc))
            await self._emit(node_id, StageEvent(stage="error", detail=str(exc)))
        finally:
            self._tasks.pop(node_id, None)

    def subscribe(self, node_id: str) -> asyncio.Queue[StageEvent]:
        queue: asyncio.Queue[StageEvent] = asyncio.Queue()
        self._subscribers.setdefault(node_id, []).append(queue)
        return queue

    def unsubscribe(self, node_id: str, queue: asyncio.Queue[StageEvent]) -> None:
        subs = self._subscribers.get(node_id, [])
        if queue in subs:
            subs.remove(queue)
        if not subs:
            self._subscribers.pop(node_id, None)

    def node_is_running(self, node_id: str) -> bool:
        return node_id in self._tasks

    async def wait_for_node(self, node_id: str) -> NodeDetail | None:
        """Block until the node's pipeline finishes (used by MCP tools)."""
        task = self._tasks.get(node_id)
        if task is not None:
            await task
        return store.get_node(self.conn, node_id)

    # ---- candidates & documents ------------------------------------------

    async def open_candidate(self, candidate_id: int) -> tuple[int | None, bool]:
        """Mark candidate opened; ensure its full text. Returns (paper_id, has_doc)."""
        paper_id = store.set_candidate_status(self.conn, candidate_id, "opened")
        if paper_id is None:
            return None, False
        async with httpx.AsyncClient(follow_redirects=True) as client:
            ok = await ensure_fulltext(self.conn, client, paper_id)
        return paper_id, ok

    def dismiss_candidate(self, candidate_id: int) -> None:
        store.set_candidate_status(self.conn, candidate_id, "dismissed")

    def restore_candidate(self, candidate_id: int) -> None:
        store.set_candidate_status(self.conn, candidate_id, "unread")

    def get_document(self, paper_id: int):
        from .fetch.fulltext import get_document
        from .pipeline.store import get_paper

        return get_paper(self.conn, paper_id), get_document(self.conn, paper_id)

    def get_passages(self, paper_id: int, query: str, k: int = 5) -> list[Passage]:
        qvec = get_embedder().embed_query(query)
        hits = VectorIndex(self.conn).search_chunks(qvec, [paper_id], k_per_paper=k)
        passages = []
        for chunk_id, score in hits.get(paper_id, []):
            row = self.conn.execute(
                "SELECT section, text FROM chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
            if row:
                passages.append(
                    Passage(chunk_id=chunk_id, section=row["section"], quote=row["text"], score=score)
                )
        return passages

    # ---- chat ---------------------------------------------------------------

    def list_chat(self, session_id: str):
        from .session import chat as chat_mod

        return chat_mod.list_messages(self.conn, session_id)

    async def chat(
        self,
        session_id: str,
        message: str,
        *,
        quote: str | None = None,
        paper_id: int | None = None,
    ):
        from .session import chat as chat_mod

        llm = self.get_llm()
        if llm is None:
            raise RuntimeError("Discussion requires a configured LLM provider")
        passages: list[str] = []
        if paper_id:
            query = f"{quote or ''} {message}".strip()
            passages = [p.quote for p in self.get_passages(paper_id, query, k=4)]
        return await chat_mod.chat(
            self.conn, llm, session_id, message,
            quote=quote, paper_id=paper_id, passages=passages,
        )

    # ---- original PDFs --------------------------------------------------------

    def pdf_path(self, paper_id: int):
        settings = get_settings()
        return settings.pdf_dir / f"{paper_id}.pdf"

    def save_pdf(self, paper_id: int, data: bytes) -> None:
        path = self.pdf_path(paper_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def ensure_pdf(self, paper_id: int) -> bool:
        """Make sure the original PDF is on disk (fetch from arXiv if needed)."""
        if self.pdf_path(paper_id).exists():
            return True
        row = self.conn.execute(
            "SELECT arxiv_id FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if not row or not row["arxiv_id"]:
            return False
        from .sources.ratelimit import polite_get

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await polite_get(
                    client,
                    f"https://arxiv.org/pdf/{row['arxiv_id']}",
                    min_interval=1.0,
                    max_retries=1,
                    timeout=60.0,
                )
            self.save_pdf(paper_id, resp.content)
            return True
        except Exception:
            logger.warning("PDF fetch failed for paper %s", paper_id)
            return False

    # ---- misc ---------------------------------------------------------------

    async def translate(
        self,
        text: str,
        target_lang: str | None = None,
        *,
        session_id: str | None = None,
        paper_id: int | None = None,
        page: int | None = None,
    ) -> str:
        lang = target_lang or store.get_settings_map(self.conn).get("translate.target_lang", "Chinese")
        # Serve a stored translation if this exact snippet was translated before.
        row = self.conn.execute(
            "SELECT translation FROM translations WHERE text = ? AND coalesce(lang,'') = ? "
            "AND coalesce(session_id,'') = coalesce(?, coalesce(session_id,''))",
            (text, lang, session_id),
        ).fetchone()
        if row:
            return row["translation"]
        llm = self.get_llm()
        if llm is None:
            raise RuntimeError("Translation requires a configured LLM provider")
        translation = await translate_snippet(text, lang, llm)
        if session_id and paper_id is not None:
            self.conn.execute(
                "INSERT INTO translations (session_id, paper_id, page, text, translation, lang) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, paper_id, page, text, translation, lang),
            )
            self.conn.commit()
        return translation

    def get_marks(self, paper_id: int, session_id: str) -> dict:
        """Everything already processed in this paper: evidence claims + translations."""
        evidence = []
        for row in self.conn.execute(
            "SELECT id, selected_text, anchor_json FROM nodes WHERE session_id = ? AND paper_id = ?",
            (session_id, paper_id),
        ):
            page = None
            if row["anchor_json"]:
                try:
                    import json as json_mod

                    page = json_mod.loads(row["anchor_json"]).get("para_start")
                except ValueError:
                    pass
            evidence.append({"node_id": row["id"], "page": page, "text": row["selected_text"]})
        translations = [
            {"id": r["id"], "page": r["page"], "text": r["text"], "translation": r["translation"]}
            for r in self.conn.execute(
                "SELECT id, page, text, translation FROM translations "
                "WHERE session_id = ? AND paper_id = ?",
                (session_id, paper_id),
            )
        ]
        return {"evidence": evidence, "translations": translations}

    def export_report(self, session_id: str) -> str:
        return export_mod.export_report(self.conn, session_id)

    def get_app_settings(self) -> dict[str, str]:
        return store.get_settings_map(self.conn)

    def update_app_settings(self, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            store.set_setting(self.conn, key, value)
        return store.get_settings_map(self.conn)


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine
