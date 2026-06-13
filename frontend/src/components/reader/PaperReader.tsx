import { useCallback, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BookX, ExternalLink, FileText, X } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { Button, Skeleton } from '@/components/ui/primitives'
import { PdfViewer } from './PdfViewer'
import { SelectionPopover } from './SelectionPopover'
import { boundingViewportRect, selectedPdfTextClientRects } from './pdfTextRects'

/** Rebuild the selected text from text-layer spans, dropping page furniture
 * that native selection sweeps up on cross-page/figure selections: bare page
 * numbers and figure/table caption lines that sit inside the selection. */
function extractCleanPdfText(range: Range, container: HTMLElement): string | null {
  const spans = Array.from(
    container.querySelectorAll<HTMLElement>('.pdf-text-layer span'),
  ).filter((sp) => range.intersectsNode(sp))
  if (!spans.length) return null

  const pieces = spans.map((sp) => {
    let t = sp.textContent ?? ''
    const isStart = sp.contains(range.startContainer) && range.startContainer.nodeType === 3
    const isEnd = sp.contains(range.endContainer) && range.endContainer.nodeType === 3
    if (isStart && isEnd) t = t.slice(range.startOffset, range.endOffset)
    else if (isStart) t = t.slice(range.startOffset)
    else if (isEnd) t = t.slice(0, range.endOffset)
    return { t, rect: sp.getBoundingClientRect() }
  })

  // visual lines occupied by figure/table captions inside the selection
  const captionBands = pieces
    .filter((p) => /^(figure|table|fig\.)\s*\d+\s*[:.]/i.test(p.t.trim()))
    .map((p) => ({ top: p.rect.top - 2, bottom: p.rect.bottom + 2 }))

  const kept: string[] = []
  pieces.forEach((p, i) => {
    const txt = p.t.trim()
    if (!txt) return
    const inMiddle = i > 0 && i < pieces.length - 1
    if (inMiddle && /^\d{1,4}$/.test(txt)) return // page number between pages
    if (captionBands.some((b) => p.rect.top < b.bottom && p.rect.bottom > b.top)) return
    kept.push(p.t)
  })
  const text = kept.join(' ').replace(/\s+/g, ' ').trim()
  return text || null
}

/** Resolve a selection inside either the PDF text layer or the HTML fallback. */
function resolveSelection(
  container: HTMLElement,
  pageText: Map<number, string>,
) {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const text = sel.toString().replace(/\s+/g, ' ').trim()
  if (text.length < 8 || text.length > 2000) return null
  const range = sel.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return null

  const closest = (node: Node, selector: string): HTMLElement | null => {
    const el = node instanceof HTMLElement ? node : node.parentElement
    return el?.closest(selector) ?? null
  }

  // PDF path: anchor to page numbers; rebuild text without page furniture
  const startPage = closest(range.startContainer, '[data-page]')
  if (startPage) {
    const endPage = closest(range.endContainer, '[data-page]') ?? startPage
    const pageStart = Number(startPage.dataset.page)
    const pageEnd = Number(endPage.dataset.page)
    if (pageEnd - pageStart > 1) return null
    const cleaned = extractCleanPdfText(range, container) ?? text
    if (cleaned.length < 8 || cleaned.length > 2000) return null
    const rect = boundingViewportRect(selectedPdfTextClientRects(container, range)) ?? range.getBoundingClientRect()
    return {
      text: cleaned,
      paraStart: pageStart,
      paraEnd: pageEnd,
      startOffset: 0,
      endOffset: 0,
      contextText: (pageText.get(pageStart) ?? '').slice(0, 2000),
      rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
    }
  }

  // HTML fallback path: data-p paragraph anchors
  const startPara = closest(range.startContainer, '[data-p]')
  const endPara = closest(range.endContainer, '[data-p]')
  if (!startPara || !endPara) return null
  const paraStart = Number(startPara.dataset.p)
  const paraEnd = Number(endPara.dataset.p)
  if (paraEnd - paraStart > 3) return null
  const rect = range.getBoundingClientRect()
  const context = [startPara.textContent ?? '', paraStart !== paraEnd ? endPara.textContent ?? '' : '']
    .filter(Boolean)
    .join(' ')
  return {
    text,
    paraStart,
    paraEnd,
    startOffset: range.startOffset,
    endOffset: range.endOffset,
    contextText: context.slice(0, 2000),
    rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
  }
}

export function PaperReader() {
  const { openPaperId, openPaper, setSelection, sessionId, setActiveNode, setTranslate } =
    useWorkbench()
  const containerRef = useRef<HTMLDivElement>(null)
  const pageTextRef = useRef<Map<number, string>>(new Map())

  const doc = useQuery({
    queryKey: ['document', openPaperId],
    queryFn: () => api.getDocument(openPaperId!),
    enabled: !!openPaperId,
    staleTime: Infinity,
  })

  const marks = useQuery({
    queryKey: ['marks', openPaperId, sessionId],
    queryFn: () => api.getMarks(openPaperId!, sessionId!),
    enabled: !!openPaperId && !!sessionId,
  })

  const handleMouseUp = useCallback(() => {
    const container = containerRef.current
    if (!container || !openPaperId) return
    const resolved = resolveSelection(container, pageTextRef.current)
    setSelection(resolved ? { ...resolved, paperId: openPaperId } : null)
  }, [openPaperId, setSelection])

  // Click on a highlighted snippet jumps to its evidence node / stored translation.
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement
      const evSpan = target.closest<HTMLElement>('span[data-node-id]')
      if (evSpan?.dataset.nodeId) {
        setActiveNode(evSpan.dataset.nodeId)
        return
      }
      const trSpan = target.closest<HTMLElement>('span[data-mark-text]')
      if (trSpan?.dataset.markText && openPaperId) {
        setTranslate({ text: trSpan.dataset.markText, paperId: openPaperId })
      }
    },
    [openPaperId, setActiveNode, setTranslate],
  )

  if (!openPaperId) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-sm text-center">
          <FileText className="mx-auto h-7 w-7 text-muted-foreground/40" />
          <h2 className="mt-3 font-serif text-lg font-semibold">No paper open</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Open a candidate from the Evidence panel, or start a new session by uploading
            the paper you want to read.
          </p>
        </div>
      </div>
    )
  }

  const paper = doc.data?.paper

  return (
    <div className="relative flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-border bg-surface px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-serif text-[15px] font-semibold">
            {paper?.title ?? 'Loading…'}
          </h1>
          {paper && (
            <p className="truncate text-[11px] text-muted-foreground">
              {paper.authors.slice(0, 4).join(', ')}
              {paper.authors.length > 4 && ' et al.'}
              {paper.year && ` · ${paper.year}`}
              {paper.arxiv_id && ` · arXiv:${paper.arxiv_id}`}
            </p>
          )}
        </div>
        {paper?.url && (
          <a
            href={paper.url}
            target="_blank"
            rel="noreferrer"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-surface-muted hover:text-foreground"
            title="Open original"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
        <Button size="icon" variant="ghost" onClick={() => openPaper(null)} title="Close paper">
          <X className="h-4 w-4" />
        </Button>
      </header>

      <div
        ref={containerRef}
        className="min-h-0 flex-1"
        onMouseUp={handleMouseUp}
        onClick={handleClick}
      >
        {doc.isLoading && (
          <div className="mx-auto max-w-[760px] space-y-3 px-8 py-10">
            <Skeleton className="h-7 w-3/4" />
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-4" style={{ width: `${85 - (i % 4) * 8}%` }} />
            ))}
          </div>
        )}

        {doc.data?.pdf_available && (
          <PdfViewer
            url={`/api/papers/${openPaperId}/pdf`}
            pageTextRef={pageTextRef}
            marks={marks.data}
          />
        )}

        {doc.data && !doc.data.pdf_available && doc.data.reader_html && (
          <div className="h-full overflow-y-auto">
            <div
              className="reader-prose mx-auto px-8 py-8"
              dangerouslySetInnerHTML={{ __html: doc.data.reader_html }}
            />
          </div>
        )}

        {doc.data && !doc.data.pdf_available && !doc.data.reader_html && (
          <div className="mx-auto max-w-md px-8 py-16 text-center">
            <BookX className="mx-auto h-6 w-6 text-muted-foreground/50" />
            <h2 className="mt-3 font-serif text-base font-semibold">Full text not available</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              No open-access version found. You can read the abstract below, or download the
              PDF from the publisher and upload it from the Evidence panel.
            </p>
            {paper?.abstract && (
              <p className="reader-prose mx-auto mt-6 text-left text-sm">{paper.abstract}</p>
            )}
          </div>
        )}
      </div>

      <SelectionPopover />
    </div>
  )
}
