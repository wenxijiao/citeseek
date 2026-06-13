"""REST + SSE routes. Thin adapter over Engine — no business logic here."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..engine import get_engine
from ..models import SelectionAnchor

router = APIRouter(prefix="/api")


# ---- request bodies ---------------------------------------------------------


class CreateSessionBody(BaseModel):
    title: str | None = None


class RenameSessionBody(BaseModel):
    title: str


class QueryBody(BaseModel):
    session_id: str
    selected_text: str
    parent_node_id: str | None = None
    paper_id: int | None = None
    anchor: SelectionAnchor | None = None
    context_text: str | None = None


class TranslateBody(BaseModel):
    text: str
    target_lang: str | None = None
    session_id: str | None = None
    paper_id: int | None = None
    page: int | None = None


class ChatBody(BaseModel):
    message: str
    quote: str | None = None
    paper_id: int | None = None


# ---- sessions ---------------------------------------------------------------


@router.post("/sessions")
def create_session(body: CreateSessionBody):
    return get_engine().create_session(body.title)


@router.get("/sessions")
def list_sessions():
    return get_engine().list_sessions()


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameSessionBody):
    get_engine().rename_session(session_id, body.title)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    get_engine().delete_session(session_id)
    return {"ok": True}


@router.post("/sessions/upload")
async def create_session_from_pdf(file: UploadFile = File(...), title: str | None = Form(None)):
    """Upload the paper the user wants to read; it becomes the session root."""
    data = await file.read()
    engine = get_engine()
    try:
        paper_id = await asyncio.to_thread(engine.upload_pdf, data, title_hint=title)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse PDF: {exc}")
    paper, _ = engine.get_document(paper_id)
    session = engine.create_session(title=paper.title, root_paper_id=paper_id)
    return {"session": session, "paper_id": paper_id}


@router.post("/papers/{paper_id}/upload")
async def upload_paper_pdf(paper_id: int, file: UploadFile = File(...)):
    """Attach a user-supplied PDF to a paywalled/unfetchable paper."""
    data = await file.read()
    engine = get_engine()
    try:
        await asyncio.to_thread(engine.upload_pdf, data, paper_id=paper_id)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse PDF: {exc}")
    return {"paper_id": paper_id, "document_ready": True}


@router.get("/sessions/{session_id}/tree")
def get_tree(session_id: str):
    return {"nodes": get_engine().get_tree(session_id)}


@router.get("/sessions/{session_id}/report")
def export_report(session_id: str):
    try:
        report = get_engine().export_report(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return Response(content=report, media_type="text/markdown; charset=utf-8")


# ---- queries & nodes ----------------------------------------------------------


@router.post("/query", status_code=202)
async def start_query(body: QueryBody):
    engine = get_engine()
    node_id = engine.start_query(
        body.session_id,
        body.selected_text,
        parent_node_id=body.parent_node_id,
        paper_id=body.paper_id,
        anchor=body.anchor,
        context_text=body.context_text,
    )
    return {"node_id": node_id}


@router.get("/nodes/{node_id}")
def get_node(node_id: str):
    node = get_engine().get_node(node_id)
    if node is None:
        raise HTTPException(404, "unknown node")
    return node


@router.get("/nodes/{node_id}/stream")
async def stream_node(node_id: str):
    engine = get_engine()
    node = engine.get_node(node_id)
    if node is None:
        raise HTTPException(404, "unknown node")

    async def generator():
        # Pipeline already finished (or errored) — replay the terminal state.
        if not engine.node_is_running(node_id):
            current = engine.get_node(node_id)
            yield {
                "event": "done" if current.status == "done" else "error",
                "data": json.dumps({"status": current.status, "error": current.error}),
            }
            return
        queue = engine.subscribe(node_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}
                    continue
                payload = {"stage": event.stage, "detail": event.detail, **(event.payload or {})}
                yield {"event": event.stage if event.stage in ("done", "error") else "stage",
                       "data": json.dumps(payload)}
                if event.stage in ("done", "error"):
                    return
        finally:
            engine.unsubscribe(node_id, queue)

    return EventSourceResponse(generator())


# ---- candidates, documents, passages ------------------------------------------


@router.post("/candidates/{candidate_id}/open")
async def open_candidate(candidate_id: int):
    paper_id, has_doc = await get_engine().open_candidate(candidate_id)
    if paper_id is None:
        raise HTTPException(404, "unknown candidate")
    return {"paper_id": paper_id, "document_ready": has_doc}


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(candidate_id: int):
    get_engine().dismiss_candidate(candidate_id)
    return {"ok": True}


@router.post("/candidates/{candidate_id}/restore")
def restore_candidate(candidate_id: int):
    get_engine().restore_candidate(candidate_id)
    return {"ok": True}


@router.get("/papers/{paper_id}/document")
def get_document(paper_id: int):
    engine = get_engine()
    paper, doc = engine.get_document(paper_id)
    if paper is None:
        raise HTTPException(404, "unknown paper")
    return {
        "paper": paper,
        "reader_html": doc["reader_html"] if doc else None,
        "available": doc is not None,
        "pdf_available": engine.pdf_path(paper_id).exists() or bool(paper.arxiv_id),
    }


@router.get("/papers/{paper_id}/pdf")
async def get_pdf(paper_id: int):
    from fastapi.responses import FileResponse

    engine = get_engine()
    ok = await engine.ensure_pdf(paper_id)
    if not ok:
        raise HTTPException(404, "no PDF available for this paper")
    return FileResponse(engine.pdf_path(paper_id), media_type="application/pdf")


@router.get("/sessions/{session_id}/chat")
def list_chat(session_id: str):
    return {"messages": get_engine().list_chat(session_id)}


@router.post("/sessions/{session_id}/chat")
async def post_chat(session_id: str, body: ChatBody):
    try:
        reply = await get_engine().chat(
            session_id, body.message, quote=body.quote, paper_id=body.paper_id
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return reply


@router.get("/papers/{paper_id}/passages")
def get_passages(paper_id: int, q: str, k: int = 5):
    return {"passages": get_engine().get_passages(paper_id, q, k)}


# ---- misc -----------------------------------------------------------------------


@router.post("/translate")
async def translate(body: TranslateBody):
    try:
        translation = await get_engine().translate(
            body.text,
            body.target_lang,
            session_id=body.session_id,
            paper_id=body.paper_id,
            page=body.page,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"translation": translation}


@router.get("/papers/{paper_id}/marks")
def get_marks(paper_id: int, session_id: str):
    return get_engine().get_marks(paper_id, session_id)


@router.get("/settings")
def get_app_settings():
    return get_engine().get_app_settings()


@router.put("/settings")
def update_app_settings(values: dict[str, str]):
    return get_engine().update_app_settings(values)
