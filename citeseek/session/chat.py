"""Per-session discussion with the LLM about the paper being read.

Retrieval-augmented: the question (plus any quoted passage) is embedded and
the most relevant indexed chunks of the paper are injected as context, along
with recent conversation history. Single-turn LLMClient, so history is
rendered into the prompt.
"""

from __future__ import annotations

from ..db import Connection
from ..llm.base import LLMClient
from ..models import ChatMessage

SYSTEM = """You are CiteSeek's reading assistant. The user is reading an academic \
paper and wants to discuss it: clarify confusing parts, probe assumptions, or \
develop their own ideas. Ground your answers in the provided excerpts when \
relevant, quote sparingly, and be direct. If the excerpts don't cover the \
question, say so and answer from general knowledge, clearly marked. Match the \
user's language (answer in Chinese if they write Chinese)."""

HISTORY_LIMIT = 12


def list_messages(conn: Connection, session_id: str) -> list[ChatMessage]:
    rows = conn.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    return [
        ChatMessage(
            id=r["id"],
            role=r["role"],
            content=r["content"],
            quote=r["quote"],
            paper_id=r["paper_id"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def _save(
    conn: Connection,
    session_id: str,
    role: str,
    content: str,
    quote: str | None = None,
    paper_id: int | None = None,
) -> ChatMessage:
    cur = conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, quote, paper_id) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, quote, paper_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return ChatMessage(
        id=row["id"], role=row["role"], content=row["content"],
        quote=row["quote"], paper_id=row["paper_id"], created_at=row["created_at"],
    )


def build_prompt(
    conn: Connection,
    session_id: str,
    message: str,
    quote: str | None,
    paper_id: int | None,
    passages: list[str],
) -> str:
    parts: list[str] = []
    if paper_id:
        paper = conn.execute("SELECT title, year FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if paper:
            parts.append(f"Paper under discussion: “{paper['title']}” ({paper['year'] or 'n.d.'})")
    if passages:
        parts.append("Relevant excerpts from the paper:\n" + "\n---\n".join(passages))

    history = list_messages(conn, session_id)[-HISTORY_LIMIT:]
    if history:
        rendered = []
        for msg in history:
            prefix = "User" if msg.role == "user" else "Assistant"
            quoted = f' (about: "{msg.quote[:150]}…")' if msg.quote else ""
            rendered.append(f"{prefix}{quoted}: {msg.content}")
        parts.append("Conversation so far:\n" + "\n".join(rendered))

    question = message
    if quote:
        question = f'Selected passage from the paper:\n"{quote}"\n\n{message}'
    parts.append(f"User's new message:\n{question}")
    return "\n\n".join(parts)


async def chat(
    conn: Connection,
    llm: LLMClient,
    session_id: str,
    message: str,
    *,
    quote: str | None = None,
    paper_id: int | None = None,
    passages: list[str] | None = None,
) -> ChatMessage:
    prompt = build_prompt(conn, session_id, message, quote, paper_id, passages or [])
    _save(conn, session_id, "user", message, quote, paper_id)
    answer = await llm.complete(SYSTEM, prompt, max_tokens=2500)
    return _save(conn, session_id, "assistant", answer.strip(), None, paper_id)
