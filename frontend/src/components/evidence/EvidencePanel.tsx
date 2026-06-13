import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Search } from 'lucide-react'
import { api } from '@/api/client'
import { streamNode } from '@/api/sse'
import type { StageEventPayload } from '@/api/types'
import { useWorkbench } from '@/stores/workbench'
import { Skeleton } from '@/components/ui/primitives'
import { CandidateCard } from './CandidateCard'
import { PipelineProgress } from './PipelineProgress'

export function EvidencePanel() {
  const { activeNodeId } = useWorkbench()
  const queryClient = useQueryClient()
  const [stages, setStages] = useState<StageEventPayload[]>([])
  const [showHidden, setShowHidden] = useState(false)
  const [renderedNodeId, setRenderedNodeId] = useState(activeNodeId)

  // Reset per-node UI state when the active node changes (render-time adjustment).
  if (renderedNodeId !== activeNodeId) {
    setRenderedNodeId(activeNodeId)
    setStages([])
    setShowHidden(false)
  }

  const node = useQuery({
    queryKey: ['node', activeNodeId],
    queryFn: () => api.getNode(activeNodeId!),
    enabled: !!activeNodeId,
  })

  const isRunning = node.data?.status === 'running' || node.data?.status === 'pending'
  const candidates = node.data?.candidates ?? []
  const visibleCandidates = candidates.filter(
    (candidate) => candidate.read_status !== 'dismissed' && candidate.verdict !== 'unrelated',
  )
  const hiddenCandidates = candidates.filter(
    (candidate) => candidate.read_status === 'dismissed' || candidate.verdict === 'unrelated',
  )

  useEffect(() => {
    if (!activeNodeId) return
    // Subscribe regardless; finished nodes immediately replay their terminal event.
    const abort = streamNode(activeNodeId, {
      onStage: (event) => setStages((prev) => [...prev.slice(-30), event]),
      onDone: () => {
        queryClient.invalidateQueries({ queryKey: ['node', activeNodeId] })
        queryClient.invalidateQueries({ queryKey: ['tree'] })
      },
      onError: () => {
        queryClient.invalidateQueries({ queryKey: ['node', activeNodeId] })
      },
    })
    return abort
  }, [activeNodeId, queryClient])

  if (!activeNodeId) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-xs text-center">
          <Search className="mx-auto h-6 w-6 text-muted-foreground/50" />
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Select a sentence in the paper and choose{' '}
            <span className="font-medium text-foreground">Find evidence</span>, or pick a node
            from the exploration tree.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-4 py-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Supporting evidence
        </p>
        <p className="mt-1 line-clamp-3 font-serif text-[13px] italic leading-5 text-foreground">
          “{node.data?.selected_text ?? '…'}”
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {isRunning && <PipelineProgress stages={stages} />}

        {node.isLoading && (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        )}

        {node.data?.status === 'error' && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm text-danger">
            Pipeline failed: {node.data.error}
          </div>
        )}

        {node.data?.status === 'done' && node.data.candidates.length === 0 && (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">
            No candidate papers found for this claim.
          </p>
        )}

        {node.data?.status === 'done' && candidates.length > 0 && visibleCandidates.length === 0 && (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">
            All candidates are hidden or marked low relevance.
          </p>
        )}

        <div className="space-y-3">
          {visibleCandidates.map((cand, i) => (
            <div
              key={cand.id}
              className="animate-fade-up"
              style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}
            >
              <CandidateCard candidate={cand} nodeId={activeNodeId} />
            </div>
          ))}
        </div>

        {hiddenCandidates.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <button
              onClick={() => setShowHidden((value) => !value)}
              className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-surface-muted hover:text-foreground"
            >
              <span>Hidden / low relevance ({hiddenCandidates.length})</span>
              <ChevronDown
                className={`h-3.5 w-3.5 transition-transform ${showHidden ? 'rotate-180' : ''}`}
              />
            </button>
            {showHidden && (
              <div className="mt-3 space-y-3">
                {hiddenCandidates.map((cand) => (
                  <CandidateCard
                    key={cand.id}
                    candidate={cand}
                    nodeId={activeNodeId}
                    hiddenReason={
                      cand.read_status === 'dismissed'
                        ? 'Hidden: dismissed'
                        : 'Low relevance: judged unrelated to this claim'
                    }
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
