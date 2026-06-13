import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { TopBar } from '@/components/layout/TopBar'
import { ClaimInput } from '@/components/layout/ClaimInput'
import { UploadDropzone } from '@/components/layout/UploadDropzone'
import { LeftPanel } from '@/components/layout/LeftPanel'
import { RightPanel } from '@/components/layout/RightPanel'
import { PaperReader } from '@/components/reader/PaperReader'
import { SettingsDialog } from '@/components/dialogs/SettingsDialog'

function Hero() {
  return (
    <div className="hero-wash flex h-full flex-col items-center justify-center px-8">
      <div className="brand-gradient flex h-12 w-12 items-center justify-center rounded-2xl shadow-lg shadow-accent/20">
        <span className="font-serif text-2xl font-bold italic text-white">C</span>
      </div>
      <h1 className="mt-6 font-serif text-4xl font-semibold tracking-tight">
        Credit where credit is&nbsp;<em className="text-accent">due</em>.
      </h1>
      <p className="mt-4 max-w-lg text-center text-[15px] leading-7 text-muted-foreground">
        Read a paper with the literature at your fingertips — select any sentence to
        trace the papers behind it, discuss it with an assistant, or translate it in
        place.
      </p>
      <div className="mt-9 w-full max-w-xl space-y-3">
        <UploadDropzone />
        <div className="flex items-center gap-3 px-2">
          <div className="h-px flex-1 bg-border" />
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
            or start from a claim
          </span>
          <div className="h-px flex-1 bg-border" />
        </div>
        <ClaimInput hero />
      </div>
      <div className="mt-10 flex flex-wrap items-center justify-center gap-x-7 gap-y-2 text-[12px] text-muted-foreground">
        <span>arXiv · Semantic Scholar · OpenAlex</span>
        <span className="hidden h-3 w-px bg-border sm:block" />
        <span>Passage-level evidence</span>
        <span className="hidden h-3 w-px bg-border sm:block" />
        <span>Confidence scores</span>
        <span className="hidden h-3 w-px bg-border sm:block" />
        <span>Exportable evidence chains</span>
      </div>
    </div>
  )
}

export default function App() {
  const {
    sessionId,
    setSession,
    activeNodeId,
    setActiveNode,
    openPaperId,
    openPaper,
    setTranslate,
    setSettingsOpen,
  } = useWorkbench()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setTranslate(null)
        setSettingsOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setTranslate, setSettingsOpen])

  // Validate the localStorage-remembered session once on first load only —
  // re-running on later (possibly stale) data would wipe freshly created sessions.
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.listSessions })
  const validatedOnce = useRef(false)
  useEffect(() => {
    if (validatedOnce.current || !sessions.data) return
    validatedOnce.current = true
    if (sessionId && !sessions.data.some((s) => s.id === sessionId)) {
      setSession(null)
    }
  }, [sessions.data, sessionId, setSession])

  // Restore the workbench after a reload / session switch: open the session's
  // root paper, or fall back to its most recent query node.
  const tree = useQuery({
    queryKey: ['tree', sessionId],
    queryFn: () => api.getTree(sessionId!),
    enabled: !!sessionId && !activeNodeId && !openPaperId,
  })
  useEffect(() => {
    if (activeNodeId || openPaperId || !sessionId) return
    const session = sessions.data?.find((s) => s.id === sessionId)
    if (session?.root_paper_id) {
      openPaper(session.root_paper_id)
    } else if (tree.data?.nodes.length) {
      setActiveNode(tree.data.nodes[tree.data.nodes.length - 1].id)
    }
  }, [activeNodeId, openPaperId, sessionId, sessions.data, tree.data, openPaper, setActiveNode])

  const empty = !sessionId || (!activeNodeId && !openPaperId)

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      {empty ? (
        <main className="min-h-0 flex-1">
          <Hero />
        </main>
      ) : (
        <main className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)_380px]">
          <aside className="flex min-h-0 flex-col border-r border-border bg-surface">
            <LeftPanel />
          </aside>
          <section className="min-h-0 bg-background">
            <PaperReader />
          </section>
          <aside className="min-h-0 border-l border-border bg-surface">
            <RightPanel />
          </aside>
        </main>
      )}
      <SettingsDialog />
    </div>
  )
}
