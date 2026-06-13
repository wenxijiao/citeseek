import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Languages, Loader2, MessagesSquare, Sparkles } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'

export function SelectionPopover() {
  const popoverRef = useRef<HTMLDivElement>(null)
  const [popoverWidth, setPopoverWidth] = useState(360)
  const {
    selection,
    sessionId,
    activeNodeId,
    setSelection,
    setActiveNode,
    setTranslate,
    setPendingQuote,
  } = useWorkbench()
  const queryClient = useQueryClient()

  const findEvidence = useMutation({
    mutationFn: async () => {
      if (!selection || !sessionId) throw new Error('no selection')
      return api.startQuery({
        session_id: sessionId,
        selected_text: selection.text,
        parent_node_id: activeNodeId,
        paper_id: selection.paperId,
        anchor: {
          para_start: selection.paraStart,
          para_end: selection.paraEnd,
          start_offset: selection.startOffset,
          end_offset: selection.endOffset,
        },
        context_text: selection.contextText,
      })
    },
    onSuccess: ({ node_id }) => {
      setSelection(null)
      window.getSelection()?.removeAllRanges()
      setActiveNode(node_id)
      queryClient.invalidateQueries({ queryKey: ['tree', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['marks'] })
    },
  })

  const translateSelection = () => {
    if (!selection) return
    setTranslate({ text: selection.text, paperId: selection.paperId, page: selection.paraStart })
    setSelection(null)
  }

  const discuss = () => {
    if (!selection) return
    setPendingQuote(selection.text)
    setSelection(null)
    window.getSelection()?.removeAllRanges()
  }

  useEffect(() => {
    if (!selection) return
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) return
      if (e.key === 'e') {
        e.preventDefault()
        findEvidence.mutate()
      } else if (e.key === 't') {
        e.preventDefault()
        translateSelection()
      } else if (e.key === 'd') {
        e.preventDefault()
        discuss()
      } else if (e.key === 'Escape') {
        setSelection(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection])

  useLayoutEffect(() => {
    if (popoverRef.current) setPopoverWidth(popoverRef.current.offsetWidth)
  }, [selection])

  if (!selection) return null

  const top = Math.max(selection.rect.top - 44, 8)
  const viewportWidth = window.innerWidth
  const centeredLeft = selection.rect.left + selection.rect.width / 2 - popoverWidth / 2
  const left = Math.min(
    Math.max(centeredLeft, 8),
    Math.max(8, viewportWidth - popoverWidth - 8),
  )

  return (
    <div
      ref={popoverRef}
      className="fixed z-50 animate-fade-in"
      style={{ top, left }}
      onMouseDown={(e) => e.preventDefault()}
    >
      <div className="flex items-center overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
        <button
          onClick={discuss}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium hover:bg-surface-muted"
        >
          <MessagesSquare className="h-3.5 w-3.5" />
          Discuss
          <kbd className="rounded bg-surface-muted px-1 text-[10px] text-muted-foreground">d</kbd>
        </button>
        <div className="h-5 w-px bg-border" />
        <button
          onClick={() => findEvidence.mutate()}
          disabled={findEvidence.isPending}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-accent hover:bg-accent-soft disabled:opacity-60"
        >
          {findEvidence.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          Find evidence
          <kbd className="rounded bg-surface-muted px-1 text-[10px] text-muted-foreground">e</kbd>
        </button>
        <div className="h-5 w-px bg-border" />
        <button
          onClick={translateSelection}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium hover:bg-surface-muted"
        >
          <Languages className="h-3.5 w-3.5" />
          Translate
          <kbd className="rounded bg-surface-muted px-1 text-[10px] text-muted-foreground">t</kbd>
        </button>
      </div>
    </div>
  )
}
