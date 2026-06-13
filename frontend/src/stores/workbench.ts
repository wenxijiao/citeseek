import { create } from 'zustand'

interface SelectionInfo {
  text: string
  paperId: number
  paraStart: number
  paraEnd: number
  startOffset: number
  endOffset: number
  contextText: string
  rect: { top: number; left: number; width: number; height: number }
}

type RightTab = 'evidence' | 'translate'
type LeftTab = 'discuss' | 'map'

export interface TranslateRequest {
  text: string
  paperId?: number | null
  page?: number | null
}

interface WorkbenchState {
  sessionId: string | null
  activeNodeId: string | null
  openPaperId: number | null
  selection: SelectionInfo | null
  translateReq: TranslateRequest | null
  pendingQuote: string | null
  jumpPage: { page: number; ts: number } | null
  rightTab: RightTab
  leftTab: LeftTab
  settingsOpen: boolean
  setSession: (id: string | null) => void
  setActiveNode: (id: string | null) => void
  openPaper: (paperId: number | null) => void
  setSelection: (sel: SelectionInfo | null) => void
  setTranslate: (req: TranslateRequest | null) => void
  setPendingQuote: (quote: string | null) => void
  jumpToPage: (page: number) => void
  setRightTab: (tab: RightTab) => void
  setLeftTab: (tab: LeftTab) => void
  setSettingsOpen: (open: boolean) => void
}

export const useWorkbench = create<WorkbenchState>((set) => ({
  sessionId: localStorage.getItem('citeseek.session'),
  activeNodeId: null,
  openPaperId: null,
  selection: null,
  translateReq: null,
  pendingQuote: null,
  jumpPage: null,
  rightTab: 'evidence',
  leftTab: 'discuss',
  settingsOpen: false,
  setSession: (id) => {
    if (id) localStorage.setItem('citeseek.session', id)
    else localStorage.removeItem('citeseek.session')
    set({ sessionId: id, activeNodeId: null, openPaperId: null, selection: null })
  },
  setActiveNode: (id) => set({ activeNodeId: id, rightTab: 'evidence' }),
  setPendingQuote: (pendingQuote) =>
    set(pendingQuote ? { pendingQuote, leftTab: 'discuss' } : { pendingQuote }),
  setLeftTab: (leftTab) => set({ leftTab }),
  openPaper: (paperId) => set({ openPaperId: paperId, selection: null }),
  setSelection: (selection) => set({ selection }),
  setTranslate: (translateReq) =>
    set(translateReq ? { translateReq, rightTab: 'translate' } : { translateReq }),
  jumpToPage: (page) => set({ jumpPage: { page, ts: Date.now() } }),
  setRightTab: (rightTab) => set({ rightTab }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
}))

export type { SelectionInfo }
