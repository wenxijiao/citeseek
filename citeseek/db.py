"""SQLite connection management and schema.

One database file holds relational data and vectors (sqlite-vec virtual
tables). WAL mode lets the API server and the MCP server share the file.
If the sqlite-vec extension cannot be loaded, callers fall back to
numpy brute-force search over embedding BLOBs (see pipeline/index.py);
the schema keeps embeddings in plain tables for that reason.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id              INTEGER PRIMARY KEY,
  arxiv_id        TEXT UNIQUE,
  doi             TEXT UNIQUE,
  s2_id           TEXT,
  openalex_id     TEXT,
  title           TEXT NOT NULL,
  title_norm      TEXT,
  abstract        TEXT,
  authors_json    TEXT,
  year            INTEGER,
  venue           TEXT,
  url             TEXT,
  open_access     INTEGER DEFAULT 0,
  citation_count  INTEGER,
  fulltext_status TEXT DEFAULT 'none',
  fulltext_format TEXT,
  created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_papers_title_norm ON papers(title_norm);

CREATE TABLE IF NOT EXISTS documents (
  paper_id    INTEGER PRIMARY KEY REFERENCES papers(id),
  reader_html TEXT,
  plain_text  TEXT,
  source_url  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
  id         INTEGER PRIMARY KEY,
  paper_id   INTEGER NOT NULL REFERENCES papers(id),
  ord        INTEGER NOT NULL,
  section    TEXT,
  para_start INTEGER,
  para_end   INTEGER,
  text       TEXT NOT NULL,
  UNIQUE(paper_id, ord)
);

-- Embeddings stored as float32 BLOBs; mirrored into sqlite-vec virtual
-- tables when the extension is available.
CREATE TABLE IF NOT EXISTS paper_embeddings (
  paper_id  INTEGER PRIMARY KEY REFERENCES papers(id),
  embedding BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id  INTEGER PRIMARY KEY REFERENCES chunks(id),
  paper_id  INTEGER NOT NULL REFERENCES papers(id),
  embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_emb_paper ON chunk_embeddings(paper_id);

CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  title         TEXT,
  root_paper_id INTEGER REFERENCES papers(id),
  created_at    TEXT DEFAULT (datetime('now')),
  updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nodes (
  id            TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL REFERENCES sessions(id),
  parent_id     TEXT REFERENCES nodes(id),
  paper_id      INTEGER REFERENCES papers(id),
  selected_text TEXT NOT NULL,
  anchor_json   TEXT,
  context_text  TEXT,
  queries_json  TEXT,
  status        TEXT DEFAULT 'pending',
  error         TEXT,
  created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nodes_session ON nodes(session_id);

CREATE TABLE IF NOT EXISTS candidates (
  id           INTEGER PRIMARY KEY,
  node_id      TEXT NOT NULL REFERENCES nodes(id),
  paper_id     INTEGER NOT NULL REFERENCES papers(id),
  rank         INTEGER NOT NULL,
  scores_json  TEXT,
  confidence   REAL,
  verdict      TEXT,
  rationale    TEXT,
  read_status  TEXT DEFAULT 'unread',
  sources_json TEXT,
  UNIQUE(node_id, paper_id)
);
CREATE INDEX IF NOT EXISTS idx_candidates_node ON candidates(node_id);

CREATE TABLE IF NOT EXISTS evidence_passages (
  id           INTEGER PRIMARY KEY,
  candidate_id INTEGER NOT NULL REFERENCES candidates(id),
  chunk_id     INTEGER REFERENCES chunks(id),
  score        REAL,
  quote        TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_candidate ON evidence_passages(candidate_id);

CREATE TABLE IF NOT EXISTS chat_messages (
  id         INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  role       TEXT NOT NULL,             -- user | assistant
  content    TEXT NOT NULL,
  quote      TEXT,                      -- selected passage the message is about
  paper_id   INTEGER REFERENCES papers(id),
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);

CREATE TABLE IF NOT EXISTS translations (
  id          INTEGER PRIMARY KEY,
  session_id  TEXT REFERENCES sessions(id),
  paper_id    INTEGER REFERENCES papers(id),
  page        INTEGER,
  text        TEXT NOT NULL,
  translation TEXT NOT NULL,
  lang        TEXT,
  created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_translations_paper ON translations(session_id, paper_id);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

EMBEDDING_DIM = 384

_VEC_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS paper_vecs USING vec0(
  paper_id INTEGER PRIMARY KEY, embedding float[{dim}]
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vecs USING vec0(
  chunk_id INTEGER PRIMARY KEY, embedding float[{dim}]
);
"""


class Connection(sqlite3.Connection):
    """sqlite3.Connection subclass that can carry the vec_enabled flag."""

    vec_enabled: bool = False


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.executescript(_VEC_SCHEMA.format(dim=EMBEDDING_DIM))
        return True
    except Exception:
        return False


def connect(db_path: str | Path = ":memory:") -> Connection:
    """Open a connection with WAL, foreign keys, and schema applied.

    The returned connection has attribute ``vec_enabled`` indicating
    whether sqlite-vec virtual tables are usable.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.executescript(SCHEMA)
    # lightweight migration for DBs created before root_paper_id existed
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    if "root_paper_id" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN root_paper_id INTEGER REFERENCES papers(id)")
    conn.vec_enabled = _try_load_sqlite_vec(conn)
    conn.commit()
    return conn
