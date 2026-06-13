import type { StageEventPayload } from '@/api/types'
import { Spinner } from '@/components/ui/primitives'

const STAGE_LABELS: Record<string, string> = {
  query_gen: 'Generating queries',
  search: 'Searching arXiv · Semantic Scholar · OpenAlex',
  dedup: 'Merging duplicates',
  first_pass: 'Ranking by relevance',
  fulltext: 'Fetching full texts',
  passages: 'Locating evidence passages',
  judge: 'Judging support with LLM',
}

export function PipelineProgress({ stages }: { stages: StageEventPayload[] }) {
  const last = stages[stages.length - 1]
  const order = Object.keys(STAGE_LABELS)
  const currentIdx = last ? order.indexOf(last.stage) : 0

  return (
    <div className="mb-4 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2.5">
        <Spinner />
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {STAGE_LABELS[last?.stage ?? 'query_gen'] ?? last?.stage ?? 'Starting…'}
          </p>
          {last?.detail && (
            <p className="truncate text-xs text-muted-foreground">{last.detail}</p>
          )}
        </div>
      </div>
      <div className="mt-3 flex gap-1">
        {order.map((stage, i) => (
          <div
            key={stage}
            className={
              'h-1 flex-1 rounded-full transition-colors duration-500 ' +
              (i <= currentIdx ? 'bg-accent' : 'bg-surface-muted')
            }
          />
        ))}
      </div>
    </div>
  )
}
