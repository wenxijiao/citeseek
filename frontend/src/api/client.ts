import type {
  ChatMessage,
  DocumentResponse,
  NodeDetail,
  NodeSummary,
  PaperMarks,
  Passage,
  QueryRequest,
  Session,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  createSession: (title?: string) =>
    request<Session>('/api/sessions', { method: 'POST', body: JSON.stringify({ title }) }),
  listSessions: () => request<Session[]>('/api/sessions'),
  renameSession: (id: string, title: string) =>
    request<{ ok: boolean }>(`/api/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),
  deleteSession: (id: string) =>
    request<{ ok: boolean }>(`/api/sessions/${id}`, { method: 'DELETE' }),
  uploadSession: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/sessions/upload', { method: 'POST', body: form })
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
    return res.json() as Promise<{ session: Session; paper_id: number }>
  },
  uploadPaperPdf: async (paperId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`/api/papers/${paperId}/upload`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
    return res.json() as Promise<{ paper_id: number; document_ready: boolean }>
  },
  getTree: (sessionId: string) =>
    request<{ nodes: NodeSummary[] }>(`/api/sessions/${sessionId}/tree`),
  startQuery: (body: QueryRequest) =>
    request<{ node_id: string }>('/api/query', { method: 'POST', body: JSON.stringify(body) }),
  getNode: (nodeId: string) => request<NodeDetail>(`/api/nodes/${nodeId}`),
  openCandidate: (candidateId: number) =>
    request<{ paper_id: number; document_ready: boolean }>(
      `/api/candidates/${candidateId}/open`,
      { method: 'POST' },
    ),
  dismissCandidate: (candidateId: number) =>
    request<{ ok: boolean }>(`/api/candidates/${candidateId}/dismiss`, { method: 'POST' }),
  restoreCandidate: (candidateId: number) =>
    request<{ ok: boolean }>(`/api/candidates/${candidateId}/restore`, { method: 'POST' }),
  getDocument: (paperId: number) => request<DocumentResponse>(`/api/papers/${paperId}/document`),
  getPassages: (paperId: number, q: string, k = 5) =>
    request<{ passages: Passage[] }>(
      `/api/papers/${paperId}/passages?q=${encodeURIComponent(q)}&k=${k}`,
    ),
  translate: (body: {
    text: string
    target_lang?: string | null
    session_id?: string | null
    paper_id?: number | null
    page?: number | null
  }) =>
    request<{ translation: string }>('/api/translate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getMarks: (paperId: number, sessionId: string) =>
    request<PaperMarks>(`/api/papers/${paperId}/marks?session_id=${sessionId}`),
  getSettings: () => request<Record<string, string>>('/api/settings'),
  updateSettings: (values: Record<string, string>) =>
    request<Record<string, string>>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(values),
    }),
  reportUrl: (sessionId: string) => `/api/sessions/${sessionId}/report`,
  listChat: (sessionId: string) =>
    request<{ messages: ChatMessage[] }>(`/api/sessions/${sessionId}/chat`),
  sendChat: (sessionId: string, body: { message: string; quote?: string | null; paper_id?: number | null }) =>
    request<ChatMessage>(`/api/sessions/${sessionId}/chat`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}
