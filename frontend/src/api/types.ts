// Mirrors of the backend Pydantic DTOs (citeseek/models.py)

export interface PaperMeta {
  arxiv_id: string | null
  doi: string | null
  s2_id: string | null
  openalex_id: string | null
  title: string
  abstract: string | null
  authors: string[]
  year: number | null
  venue: string | null
  url: string | null
  open_access: boolean
  citation_count: number | null
  sources: string[]
}

export interface Passage {
  chunk_id: number | null
  section: string | null
  quote: string
  score: number
}

export interface CandidateScores {
  embed: number | null
  bm25: number | null
  llm: number | null
  year_prior: number | null
  final: number
}

export type ReadStatus = 'unread' | 'opened' | 'dismissed'

export interface Candidate {
  id: number
  rank: number
  paper_id: number
  paper: PaperMeta
  scores: CandidateScores
  confidence: number | null
  verdict: string | null
  rationale: string | null
  read_status: ReadStatus
  passages: Passage[]
}

export type NodeStatus = 'pending' | 'running' | 'done' | 'error'

export interface NodeSummary {
  id: string
  session_id: string
  parent_id: string | null
  paper_id: number | null
  paper_title: string | null
  selected_text: string
  anchor_page: number | null
  status: NodeStatus
  candidate_count: number
  unread_count: number
  created_at: string | null
}

export interface PaperMarks {
  evidence: { node_id: string; page: number | null; text: string }[]
  translations: { id: number; page: number | null; text: string; translation: string }[]
}

export interface NodeDetail extends NodeSummary {
  context_text: string | null
  queries: string[]
  error: string | null
  candidates: Candidate[]
}

export interface Session {
  id: string
  title: string | null
  root_paper_id: number | null
  root_paper_title: string | null
  created_at: string | null
  updated_at: string | null
  node_count: number
}

export interface SelectionAnchor {
  para_start: number
  para_end: number
  start_offset: number
  end_offset: number
}

export interface QueryRequest {
  session_id: string
  selected_text: string
  parent_node_id?: string | null
  paper_id?: number | null
  anchor?: SelectionAnchor | null
  context_text?: string | null
}

export interface DocumentResponse {
  paper: PaperMeta
  reader_html: string | null
  available: boolean
  pdf_available: boolean
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  quote: string | null
  paper_id: number | null
  created_at: string | null
}

export interface StageEventPayload {
  stage: string
  detail: string | null
  [key: string]: unknown
}
