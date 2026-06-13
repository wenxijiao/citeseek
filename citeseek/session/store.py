"""CRUD for sessions, exploration-tree nodes, and candidate lists."""

from __future__ import annotations

import json
import uuid

from ..db import Connection
from ..models import (
    Candidate,
    CandidateScores,
    NodeDetail,
    NodeSummary,
    Passage,
    SelectionAnchor,
    Session,
)
from ..pipeline.store import row_to_meta


def _row_to_session(row, node_count: int = 0) -> Session:
    keys = row.keys()
    return Session(
        id=row["id"],
        title=row["title"],
        root_paper_id=row["root_paper_id"],
        root_paper_title=row["root_paper_title"] if "root_paper_title" in keys else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        node_count=node_count,
    )


def create_session(
    conn: Connection, title: str | None = None, root_paper_id: int | None = None
) -> Session:
    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sessions (id, title, root_paper_id) VALUES (?, ?, ?)",
        (session_id, title, root_paper_id),
    )
    conn.commit()
    return get_session(conn, session_id)


def list_sessions(conn: Connection) -> list[Session]:
    rows = conn.execute(
        """SELECT s.*, p.title AS root_paper_title,
                  (SELECT count(*) FROM nodes n WHERE n.session_id = s.id) AS node_count
           FROM sessions s LEFT JOIN papers p ON p.id = s.root_paper_id
           ORDER BY s.updated_at DESC"""
    ).fetchall()
    return [_row_to_session(r, r["node_count"]) for r in rows]


def get_session(conn: Connection, session_id: str) -> Session | None:
    row = conn.execute(
        """SELECT s.*, p.title AS root_paper_title
           FROM sessions s LEFT JOIN papers p ON p.id = s.root_paper_id
           WHERE s.id = ?""",
        (session_id,),
    ).fetchone()
    return _row_to_session(row) if row else None


def delete_session(conn: Connection, session_id: str) -> None:
    conn.execute(
        """DELETE FROM evidence_passages WHERE candidate_id IN
           (SELECT c.id FROM candidates c JOIN nodes n ON n.id = c.node_id
            WHERE n.session_id = ?)""",
        (session_id,),
    )
    conn.execute(
        "DELETE FROM candidates WHERE node_id IN (SELECT id FROM nodes WHERE session_id = ?)",
        (session_id,),
    )
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    # break the self-referencing FK before bulk delete
    conn.execute("UPDATE nodes SET parent_id = NULL WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM nodes WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def touch_session(conn: Connection, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?", (session_id,)
    )
    conn.commit()


def rename_session(conn: Connection, session_id: str, title: str) -> None:
    conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
    conn.commit()


def create_node(
    conn: Connection,
    session_id: str,
    selected_text: str,
    *,
    parent_id: str | None = None,
    paper_id: int | None = None,
    anchor: SelectionAnchor | None = None,
    context_text: str | None = None,
) -> str:
    node_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO nodes (id, session_id, parent_id, paper_id, selected_text,
                              anchor_json, context_text, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            node_id,
            session_id,
            parent_id,
            paper_id,
            selected_text,
            anchor.model_dump_json() if anchor else None,
            context_text,
        ),
    )
    conn.commit()
    touch_session(conn, session_id)
    return node_id


def set_node_status(
    conn: Connection,
    node_id: str,
    status: str,
    *,
    error: str | None = None,
    queries: list[str] | None = None,
) -> None:
    conn.execute(
        "UPDATE nodes SET status = ?, error = ?, queries_json = coalesce(?, queries_json) WHERE id = ?",
        (status, error, json.dumps(queries) if queries else None, node_id),
    )
    conn.commit()


def save_candidates(conn: Connection, node_id: str, candidates: list[Candidate]) -> None:
    conn.execute("DELETE FROM evidence_passages WHERE candidate_id IN (SELECT id FROM candidates WHERE node_id = ?)", (node_id,))
    conn.execute("DELETE FROM candidates WHERE node_id = ?", (node_id,))
    for cand in candidates:
        cur = conn.execute(
            """INSERT INTO candidates (node_id, paper_id, rank, scores_json, confidence,
                                       verdict, rationale, read_status, sources_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'unread', ?)""",
            (
                node_id,
                cand.paper_id,
                cand.rank,
                cand.scores.model_dump_json(),
                cand.confidence,
                cand.verdict,
                cand.rationale,
                json.dumps(cand.paper.sources),
            ),
        )
        cand.id = cur.lastrowid
        for passage in cand.passages:
            conn.execute(
                "INSERT INTO evidence_passages (candidate_id, chunk_id, score, quote) VALUES (?, ?, ?, ?)",
                (cand.id, passage.chunk_id, passage.score, passage.quote),
            )
    conn.commit()


def _load_candidates(conn: Connection, node_id: str) -> list[Candidate]:
    rows = conn.execute(
        """SELECT c.*, p.* , c.id AS cand_id
           FROM candidates c JOIN papers p ON p.id = c.paper_id
           WHERE c.node_id = ? ORDER BY c.rank""",
        (node_id,),
    ).fetchall()
    candidates = []
    for row in rows:
        passages = [
            Passage(
                chunk_id=pr["chunk_id"],
                quote=pr["quote"],
                score=pr["score"] or 0.0,
                section=pr["section"],
            )
            for pr in conn.execute(
                """SELECT ep.*, ch.section FROM evidence_passages ep
                   LEFT JOIN chunks ch ON ch.id = ep.chunk_id
                   WHERE ep.candidate_id = ? ORDER BY ep.score DESC""",
                (row["cand_id"],),
            ).fetchall()
        ]
        meta = row_to_meta(row)
        meta.sources = json.loads(row["sources_json"] or "[]")
        candidates.append(
            Candidate(
                id=row["cand_id"],
                rank=row["rank"],
                paper_id=row["paper_id"],
                paper=meta,
                scores=CandidateScores.model_validate_json(row["scores_json"] or "{}"),
                confidence=row["confidence"],
                verdict=row["verdict"],
                rationale=row["rationale"],
                read_status=row["read_status"],
                passages=passages,
            )
        )
    return candidates


def _node_counts(conn: Connection, node_id: str) -> tuple[int, int]:
    row = conn.execute(
        """SELECT count(*) AS total,
                  sum(CASE WHEN read_status = 'unread' THEN 1 ELSE 0 END) AS unread
           FROM candidates WHERE node_id = ?""",
        (node_id,),
    ).fetchone()
    return row["total"] or 0, row["unread"] or 0


def _row_to_summary(conn: Connection, row) -> NodeSummary:
    total, unread = _node_counts(conn, row["id"])
    paper_title = None
    if row["paper_id"]:
        prow = conn.execute("SELECT title FROM papers WHERE id = ?", (row["paper_id"],)).fetchone()
        paper_title = prow["title"] if prow else None
    anchor_page = None
    if row["anchor_json"]:
        try:
            anchor_page = json.loads(row["anchor_json"]).get("para_start")
        except (ValueError, AttributeError):
            pass
    return NodeSummary(
        id=row["id"],
        session_id=row["session_id"],
        parent_id=row["parent_id"],
        paper_id=row["paper_id"],
        paper_title=paper_title,
        selected_text=row["selected_text"],
        anchor_page=anchor_page,
        status=row["status"],
        candidate_count=total,
        unread_count=unread,
        created_at=row["created_at"],
    )


def get_tree(conn: Connection, session_id: str) -> list[NodeSummary]:
    rows = conn.execute(
        "SELECT * FROM nodes WHERE session_id = ? ORDER BY created_at", (session_id,)
    ).fetchall()
    return [_row_to_summary(conn, r) for r in rows]


def get_node(conn: Connection, node_id: str) -> NodeDetail | None:
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    summary = _row_to_summary(conn, row)
    return NodeDetail(
        **summary.model_dump(),
        context_text=row["context_text"],
        queries=json.loads(row["queries_json"] or "[]"),
        error=row["error"],
        candidates=_load_candidates(conn, node_id),
    )


def set_candidate_status(conn: Connection, candidate_id: int, status: str) -> int | None:
    """Mark a candidate opened/dismissed/unread; returns its paper_id."""
    row = conn.execute("SELECT paper_id FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE candidates SET read_status = ? WHERE id = ?", (status, candidate_id))
    conn.commit()
    return row["paper_id"]


def get_settings_map(conn: Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}


def set_setting(conn: Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
