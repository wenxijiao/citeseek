import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CircleAlert,
  Download,
  FilePlus2,
  FileText,
  GitBranch,
  Loader2,
  MessageSquareQuote,
} from 'lucide-react'
import { api } from '@/api/client'
import type { NodeSummary } from '@/api/types'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'
import { Badge, Skeleton } from '@/components/ui/primitives'

function NodeRow({ node, depth }: { node: NodeSummary; depth: number }) {
  const { activeNodeId, setActiveNode, openPaperId, openPaper, jumpToPage } = useWorkbench()
  const isActive = node.id === activeNodeId
  const activate = () => {
    setActiveNode(node.id)
    // Show the sentence's source: open the paper it was selected in and
    // scroll to the anchored page.
    if (node.paper_id) {
      if (node.paper_id !== openPaperId) openPaper(node.paper_id)
      if (node.anchor_page != null) jumpToPage(node.anchor_page)
    }
  }
  return (
    <button
      onClick={activate}
      className={cn(
        'group w-full text-left rounded-lg px-2.5 py-2 transition-colors',
        isActive ? 'bg-accent-soft' : 'hover:bg-surface-muted',
      )}
      style={{ marginLeft: depth * 14, width: `calc(100% - ${depth * 14}px)` }}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0 text-muted-foreground">
          {node.status === 'running' || node.status === 'pending' ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
          ) : node.status === 'error' ? (
            <CircleAlert className="h-3.5 w-3.5 text-danger" />
          ) : depth === 0 ? (
            <MessageSquareQuote className="h-3.5 w-3.5" />
          ) : (
            <GitBranch className="h-3.5 w-3.5" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              'block truncate text-[13px] leading-5',
              isActive ? 'text-accent font-medium' : 'text-foreground',
            )}
          >
            {node.selected_text}
          </span>
          {node.paper_title && (
            <span className="block truncate text-[11px] text-muted-foreground">
              from {node.paper_title}
            </span>
          )}
        </span>
        {node.unread_count > 0 && (
          <Badge tone="accent" className="shrink-0 tabular-nums">
            {node.unread_count}
          </Badge>
        )}
      </div>
    </button>
  )
}

function RootPaperRow() {
  const { sessionId, openPaperId, openPaper } = useWorkbench()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.listSessions })
  const session = sessions.data?.find((s) => s.id === sessionId)
  if (!session?.root_paper_id) return null
  const isOpen = openPaperId === session.root_paper_id
  return (
    <button
      onClick={() => openPaper(session.root_paper_id)}
      className={cn(
        'mb-1 w-full rounded-lg border px-2.5 py-2 text-left transition-colors',
        isOpen
          ? 'border-accent/40 bg-accent-soft'
          : 'border-border hover:bg-surface-muted',
      )}
    >
      <span className="flex items-center gap-2">
        <FileText className="h-3.5 w-3.5 shrink-0 text-accent" />
        <span className="min-w-0">
          <span className={cn('block truncate text-[13px] font-medium', isOpen && 'text-accent')}>
            {session.root_paper_title || 'This paper'}
          </span>
          <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">
            the paper you’re reading
          </span>
        </span>
      </span>
    </button>
  )
}

export function TreeSidebar() {
  const { sessionId } = useWorkbench()
  const queryClient = useQueryClient()
  const tree = useQuery({
    queryKey: ['tree', sessionId],
    queryFn: () => api.getTree(sessionId!),
    enabled: !!sessionId,
    refetchInterval: (query) =>
      query.state.data?.nodes.some((n) => n.status === 'running' || n.status === 'pending')
        ? 2500
        : false,
  })

  if (!sessionId) return null

  const nodes = tree.data?.nodes ?? []
  const byParent = new Map<string | null, NodeSummary[]>()
  for (const node of nodes) {
    const list = byParent.get(node.parent_id) ?? []
    list.push(node)
    byParent.set(node.parent_id, list)
  }

  const rows: { node: NodeSummary; depth: number }[] = []
  const walk = (parentId: string | null, depth: number) => {
    for (const node of byParent.get(parentId) ?? []) {
      rows.push({ node, depth })
      walk(node.id, depth + 1)
    }
  }
  walk(null, 0)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 pt-3 pb-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Exploration
        </h2>
        {nodes.length > 0 && (
          <a
            href={api.reportUrl(sessionId)}
            download={`citeseek-report.md`}
            title="Export evidence-chain report"
            className="text-muted-foreground hover:text-accent transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-1.5 pb-3 space-y-0.5">
        <RootPaperRow />
        {tree.isLoading && (
          <div className="space-y-2 px-2 pt-1">
            <Skeleton className="h-9" />
            <Skeleton className="h-9 w-5/6" />
            <Skeleton className="h-9 w-4/6" />
          </div>
        )}
        {!tree.isLoading && rows.length === 0 && (
          <div className="px-3 py-6 text-center">
            <FilePlus2 className="mx-auto h-5 w-5 text-muted-foreground/60" />
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Ask about a claim below to start exploring the literature.
            </p>
          </div>
        )}
        {rows.map(({ node, depth }) => (
          <NodeRow key={node.id} node={node} depth={depth} />
        ))}
      </div>
      {nodes.some((n) => n.status === 'running') && (
        <button
          className="mx-3 mb-2 text-[11px] text-muted-foreground hover:text-accent text-left"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['tree', sessionId] })}
        >
          refresh
        </button>
      )}
    </div>
  )
}
