import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  ChevronDown,
  ExternalLink,
  EyeOff,
  FileUp,
  Loader2,
  Quote,
  RotateCcw,
} from 'lucide-react'
import { api } from '@/api/client'
import type { Candidate } from '@/api/types'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'
import { Badge, Button } from '@/components/ui/primitives'

function ConfidenceBadge({ candidate }: { candidate: Candidate }) {
  if (candidate.confidence == null) {
    return <Badge>score {candidate.scores.final.toFixed(2)}</Badge>
  }
  const pct = Math.round(candidate.confidence * 100)
  const tone =
    candidate.confidence >= 0.75 ? 'positive' : candidate.confidence >= 0.45 ? 'warning' : 'neutral'
  return <Badge tone={tone}>{pct}% confidence</Badge>
}

const VERDICT_LABEL: Record<string, string> = {
  supports: 'Supports',
  partially_supports: 'Partially supports',
  background: 'Background',
  unrelated: 'Unrelated',
}

export function CandidateCard({
  candidate,
  nodeId,
  hiddenReason,
}: {
  candidate: Candidate
  nodeId: string
  hiddenReason?: string
}) {
  const { paper } = candidate
  const [expanded, setExpanded] = useState(false)
  const { openPaper } = useWorkbench()
  const queryClient = useQueryClient()

  const open = useMutation({
    mutationFn: () => api.openCandidate(candidate.id),
    onSuccess: ({ paper_id }) => {
      openPaper(paper_id)
      queryClient.invalidateQueries({ queryKey: ['node', nodeId] })
      queryClient.invalidateQueries({ queryKey: ['tree'] })
    },
  })

  const dismiss = useMutation({
    mutationFn: () => api.dismissCandidate(candidate.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['node', nodeId] })
      queryClient.invalidateQueries({ queryKey: ['tree'] })
    },
  })

  const restore = useMutation({
    mutationFn: () => api.restoreCandidate(candidate.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['node', nodeId] })
      queryClient.invalidateQueries({ queryKey: ['tree'] })
    },
  })

  const fileRef = useRef<HTMLInputElement>(null)
  const uploadPdf = useMutation({
    mutationFn: (file: File) => api.uploadPaperPdf(candidate.paper_id, file),
    onSuccess: async () => {
      await api.openCandidate(candidate.id).catch(() => {})
      queryClient.invalidateQueries({ queryKey: ['document', candidate.paper_id] })
      queryClient.invalidateQueries({ queryKey: ['node', nodeId] })
      openPaper(candidate.paper_id)
    },
  })

  const canRead = !!paper.arxiv_id

  return (
    <article
      className={cn(
        'group card-elevated rounded-xl border border-border bg-surface p-3.5 transition-shadow',
        candidate.read_status === 'opened' && 'opacity-80',
        hiddenReason && 'border-dashed opacity-75',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-semibold tabular-nums text-muted-foreground">
          #{candidate.rank}
        </span>
        <div className="flex items-center gap-1.5">
          {candidate.verdict && (
            <Badge tone={candidate.verdict === 'supports' ? 'positive' : 'neutral'}>
              {VERDICT_LABEL[candidate.verdict] ?? candidate.verdict}
            </Badge>
          )}
          <ConfidenceBadge candidate={candidate} />
        </div>
      </div>

      <h3 className="mt-1.5 font-serif text-[15px] font-semibold leading-snug">
        {paper.title}
      </h3>
      {hiddenReason && (
        <p className="mt-1 text-[11px] font-medium text-muted-foreground">{hiddenReason}</p>
      )}
      <p className="mt-0.5 text-xs text-muted-foreground">
        {paper.authors.slice(0, 3).join(', ')}
        {paper.authors.length > 3 && ' et al.'}
        {paper.year && <span> · {paper.year}</span>}
        {paper.venue && <span> · {paper.venue}</span>}
        {paper.citation_count != null && (
          <span> · {paper.citation_count.toLocaleString()} citations</span>
        )}
      </p>

      {candidate.rationale && (
        <p className="mt-2 text-[13px] leading-5 text-foreground/85">{candidate.rationale}</p>
      )}

      {candidate.passages.length > 0 && (
        <div className="mt-2">
          <button
            onClick={() => setExpanded((e) => !e)}
            className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
          >
            <Quote className="h-3 w-3" />
            {candidate.passages.length} evidence passage
            {candidate.passages.length > 1 ? 's' : ''}
            <ChevronDown
              className={cn('h-3 w-3 transition-transform', expanded && 'rotate-180')}
            />
          </button>
          {expanded && (
            <div className="mt-2 space-y-2">
              {candidate.passages.map((p, i) => (
                <blockquote
                  key={i}
                  className="rounded-lg border-l-2 border-accent bg-surface-muted px-3 py-2 font-serif text-[13px] leading-5"
                >
                  {p.section && (
                    <span className="mb-0.5 block font-sans text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {p.section}
                    </span>
                  )}
                  {p.quote}
                </blockquote>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mt-3 flex items-center gap-1.5">
        {canRead ? (
          <Button size="sm" variant="subtle" onClick={() => open.mutate()} disabled={open.isPending}>
            {open.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <BookOpen className="h-3 w-3" />
            )}
            Read here
          </Button>
        ) : (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) uploadPdf.mutate(f)
              }}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => fileRef.current?.click()}
              disabled={uploadPdf.isPending}
              title="No open-access version found — upload the PDF yourself to read it here"
            >
              {uploadPdf.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <FileUp className="h-3 w-3" />
              )}
              Upload PDF
            </Button>
          </>
        )}
        {paper.url && (
          <a
            href={paper.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:bg-surface-muted hover:text-foreground"
          >
            <ExternalLink className="h-3 w-3" />
            Source
          </a>
        )}
        {candidate.read_status === 'dismissed' ? (
          <button
            onClick={() => restore.mutate()}
            title="Restore"
            className="ml-auto inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:bg-surface-muted hover:text-foreground"
          >
            {restore.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RotateCcw className="h-3 w-3" />
            )}
            Restore
          </button>
        ) : (
          <button
            onClick={() => dismiss.mutate()}
            title="Dismiss"
            className="ml-auto rounded-md p-1.5 text-muted-foreground/60 opacity-0 transition-opacity hover:bg-surface-muted hover:text-foreground group-hover:opacity-100"
          >
            <EyeOff className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </article>
  )
}
