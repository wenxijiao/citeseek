import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Languages } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/primitives'

function Item({
  text,
  translation,
  active,
  onClick,
}: {
  text: string
  translation: string | null
  active: boolean
  onClick: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [active])
  return (
    <div
      ref={ref}
      onClick={onClick}
      className={cn(
        'cursor-pointer rounded-xl border px-3.5 py-3 transition-colors',
        active ? 'border-accent/50 bg-accent-soft/40' : 'border-border bg-surface hover:bg-surface-muted/60',
      )}
    >
      <p
        className={cn(
          'font-serif text-[12px] italic leading-5 text-muted-foreground',
          !active && 'line-clamp-2',
        )}
      >
        “{text}”
      </p>
      <div className="mt-2 border-t border-border/70 pt-2">
        {translation === null ? (
          <div className="space-y-1.5">
            <Skeleton className="h-3.5" />
            <Skeleton className="h-3.5 w-4/5" />
          </div>
        ) : (
          <p className={cn('text-[13px] leading-6', !active && 'line-clamp-3')}>{translation}</p>
        )}
      </div>
    </div>
  )
}

/** Right-panel tab: every translation made in the currently open paper. */
export function TranslatePanel() {
  const { translateReq, sessionId, openPaperId, setTranslate } = useWorkbench()
  const queryClient = useQueryClient()

  const marks = useQuery({
    queryKey: ['marks', openPaperId, sessionId],
    queryFn: () => api.getMarks(openPaperId!, sessionId!),
    enabled: !!openPaperId && !!sessionId,
  })
  const stored = marks.data?.translations ?? []

  // The request being viewed/created, only if it belongs to this paper.
  const activeReq =
    translateReq && (translateReq.paperId == null || translateReq.paperId === openPaperId)
      ? translateReq
      : null
  const isNew = !!activeReq && !stored.some((t) => t.text === activeReq.text)

  const fresh = useQuery({
    queryKey: ['translate', activeReq?.text],
    queryFn: () =>
      api.translate({
        text: activeReq!.text,
        session_id: sessionId,
        paper_id: activeReq!.paperId ?? openPaperId,
        page: activeReq!.page ?? null,
      }),
    enabled: !!activeReq && isNew,
    staleTime: Infinity,
    retry: false,
  })

  useEffect(() => {
    if (fresh.data) queryClient.invalidateQueries({ queryKey: ['marks'] })
  }, [fresh.data, queryClient])

  const items = [...stored].reverse()

  if (!openPaperId || (items.length === 0 && !isNew)) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-xs text-center">
          <Languages className="mx-auto h-6 w-6 text-muted-foreground/50" />
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {openPaperId
              ? 'Nothing translated in this paper yet — select a passage and choose '
              : 'Open a paper, then select a passage and choose '}
            <span className="font-medium text-foreground">Translate</span>. Every
            translation is kept here, per paper.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full space-y-2.5 overflow-y-auto p-3">
      {isNew && activeReq && (
        <Item
          text={activeReq.text}
          translation={
            fresh.data?.translation ??
            (fresh.isError ? '⚠ Translation failed — check the LLM provider in Settings.' : null)
          }
          active
          onClick={() => {}}
        />
      )}
      {items.map((t) => (
        <Item
          key={t.id}
          text={t.text}
          translation={t.translation}
          active={activeReq?.text === t.text}
          onClick={() => setTranslate({ text: t.text, paperId: openPaperId, page: t.page })}
        />
      ))}
    </div>
  )
}
