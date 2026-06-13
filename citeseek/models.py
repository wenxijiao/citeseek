"""Shared Pydantic DTOs used by the pipeline, REST API, MCP server, and CLI."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaperMeta(BaseModel):
    """Normalized paper metadata from any scholarly source."""

    arxiv_id: str | None = None
    doi: str | None = None
    s2_id: str | None = None
    openalex_id: str | None = None
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    open_access: bool = False
    citation_count: int | None = None
    sources: list[str] = Field(default_factory=list)


class Passage(BaseModel):
    chunk_id: int | None = None
    section: str | None = None
    quote: str
    score: float = 0.0


class CandidateScores(BaseModel):
    embed: float | None = None
    bm25: float | None = None
    llm: float | None = None
    year_prior: float | None = None
    cite_freq: float | None = None
    survey_penalty: float | None = None
    final: float = 0.0


class Candidate(BaseModel):
    id: int | None = None
    rank: int
    paper_id: int
    paper: PaperMeta
    scores: CandidateScores = Field(default_factory=CandidateScores)
    confidence: float | None = None
    verdict: str | None = None
    rationale: str | None = None
    read_status: str = "unread"
    passages: list[Passage] = Field(default_factory=list)


class SelectionAnchor(BaseModel):
    """Position of a text selection inside reader_html (data-p paragraphs)."""

    para_start: int
    para_end: int
    start_offset: int
    end_offset: int


class NodeSummary(BaseModel):
    id: str
    session_id: str
    parent_id: str | None = None
    paper_id: int | None = None
    paper_title: str | None = None
    selected_text: str
    anchor_page: int | None = None
    status: str = "pending"
    candidate_count: int = 0
    unread_count: int = 0
    created_at: str | None = None


class NodeDetail(NodeSummary):
    context_text: str | None = None
    queries: list[str] = Field(default_factory=list)
    error: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)


class Session(BaseModel):
    id: str
    title: str | None = None
    root_paper_id: int | None = None
    root_paper_title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    node_count: int = 0


class QueryPlan(BaseModel):
    """LLM output: search queries derived from a claim."""

    queries: list[str] = Field(min_length=1, max_length=6)
    concepts: list[str] = Field(default_factory=list)


class Judgment(BaseModel):
    """LLM judge output for one candidate."""

    ref: int = Field(description="Index of the candidate in the batch")
    verdict: str = Field(description="supports | partially_supports | background | unrelated")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    best_quote: str | None = None


class JudgmentBatch(BaseModel):
    judgments: list[Judgment]


class ParsedDoc(BaseModel):
    """Result of full-text parsing (HTML or PDF)."""

    title: str | None = None
    reader_html: str
    plain_text: str
    sections: list[str] = Field(default_factory=list)
    source_url: str | None = None
    format: str = "arxiv_html"  # arxiv_html | ar5iv | pdf


class ChatMessage(BaseModel):
    id: int | None = None
    role: str
    content: str
    quote: str | None = None
    paper_id: int | None = None
    created_at: str | None = None


class StageEvent(BaseModel):
    """Progress event emitted by the pipeline (SSE / MCP progress)."""

    stage: str
    detail: str | None = None
    payload: dict | None = None
