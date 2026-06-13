import { useEffect, useMemo, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import type { PaperMarks } from '@/api/types'
import { useWorkbench } from '@/stores/workbench'
import { Skeleton } from '@/components/ui/primitives'
import {
  clientRectsToLineBands,
  selectedPdfTextClientRects,
  type TextClientRect,
  visibleWordClientRects,
} from './pdfTextRects'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export interface Mark {
  kind: 'evidence' | 'translate'
  text: string
  nodeId?: string
}

interface PdfViewerProps {
  url: string
  /** Map of page number -> plain text, filled as pages render (for selection context). */
  pageTextRef: React.MutableRefObject<Map<number, string>>
  marks?: PaperMarks
}

interface MarkRect {
  kind: 'evidence' | 'translate'
  nodeId?: string
  markText?: string
  t: number
  l: number
  w: number
  h: number
}

/** Locate already-processed snippets by fuzzy-matching their text across the
 * page's text-layer spans, then emit whitespace-trimmed glyph rectangles for
 * a highlight overlay (span boxes themselves bleed across justification
 * gaps). Spans also get data attributes so clicks can resolve the mark. */
function computeMarkRects(
  container: HTMLElement,
  pageHost: HTMLElement,
  marks: Mark[],
): MarkRect[] {
  const spans = Array.from(container.querySelectorAll<HTMLSpanElement>('span'))
  for (const sp of spans) {
    delete sp.dataset.nodeId
    delete sp.dataset.markText
  }
  if (!marks.length || !spans.length) return []
  const norm = (t: string) => t.replace(/\s+/g, ' ').trim().toLowerCase()
  let big = ''
  const owner: number[] = []
  spans.forEach((sp, i) => {
    const t = norm(sp.textContent ?? '')
    if (!t) return
    if (big) {
      big += ' '
      owner.push(-1)
    }
    for (let k = 0; k < t.length; k++) owner.push(i)
    big += t
  })

  const out: MarkRect[] = []
  for (const mark of marks) {
    const needle = norm(mark.text)
    if (needle.length < 8) continue
    const idx = big.indexOf(needle)
    if (idx < 0) continue
    const touched = [...new Set(owner.slice(idx, idx + needle.length))].filter((i) => i >= 0)
    const rects: TextClientRect[] = []
    for (const i of touched) {
      const sp = spans[i]
      if (mark.kind === 'evidence' && mark.nodeId) sp.dataset.nodeId = mark.nodeId
      if (mark.kind === 'translate') sp.dataset.markText = mark.text
      const tn = sp.firstChild
      if (!tn || tn.nodeType !== Node.TEXT_NODE) continue
      const text = tn.textContent ?? ''
      let start = 0
      let end = text.length
      while (end > start && /\s/.test(text[end - 1])) end--
      while (start < end && /\s/.test(text[start])) start++
      if (start >= end) continue
      rects.push(...visibleWordClientRects(sp, tn, start, end))
    }
    out.push(
      ...clientRectsToLineBands(rects, pageHost).map((band) => ({
        kind: mark.kind,
        nodeId: mark.nodeId,
        markText: mark.kind === 'translate' ? mark.text : undefined,
        t: band.t,
        l: band.l,
        w: band.w,
        h: band.h,
      })),
    )
  }
  return out
}

function PdfPage({
  doc,
  pageNumber,
  width,
  pageTextRef,
  marks,
}: {
  doc: PDFDocumentProxy
  pageNumber: number
  width: number
  pageTextRef: PdfViewerProps['pageTextRef']
  marks: Mark[]
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const textRef = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(width * 1.294)
  const [rendered, setRendered] = useState(false)
  const hostRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(pageNumber <= 3)
  const [markRects, setMarkRects] = useState<MarkRect[]>([])

  // Lazy-render pages as they approach the viewport.
  useEffect(() => {
    if (visible || !hostRef.current) return
    const observer = new IntersectionObserver(
      (entries) => entries[0].isIntersecting && setVisible(true),
      { rootMargin: '1200px' },
    )
    observer.observe(hostRef.current)
    return () => observer.disconnect()
  }, [visible])

  useEffect(() => {
    if (!visible || rendered) return
    let cancelled = false
    ;(async () => {
      const page = await doc.getPage(pageNumber)
      if (cancelled) return
      const base = page.getViewport({ scale: 1 })
      const scale = width / base.width
      const viewport = page.getViewport({ scale })
      setHeight(viewport.height)

      const canvas = canvasRef.current!
      const dpr = window.devicePixelRatio || 1
      canvas.width = viewport.width * dpr
      canvas.height = viewport.height * dpr
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      await page.render({
        canvas,
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      }).promise
      if (cancelled) return

      // Selectable text layer
      const container = textRef.current!
      container.innerHTML = ''
      container.style.setProperty('--scale-factor', String(scale))
      const textLayer = new pdfjs.TextLayer({
        textContentSource: page.streamTextContent(),
        container,
        viewport,
      })
      await textLayer.render()

      const textContent = await page.getTextContent()
      pageTextRef.current.set(
        pageNumber,
        textContent.items.map((it) => ('str' in it ? it.str : '')).join(' '),
      )
      if (!cancelled) setRendered(true)
    })().catch(() => {})
    return () => {
      cancelled = true
    }
  }, [visible, rendered, doc, pageNumber, width, pageTextRef])

  useEffect(() => {
    if (rendered && textRef.current && hostRef.current) {
      setMarkRects(computeMarkRects(textRef.current, hostRef.current, marks))
    }
  }, [rendered, marks])

  return (
    <div
      ref={hostRef}
      data-page={pageNumber}
      className="relative mx-auto mb-4 bg-white shadow-md dark:shadow-black/40"
      style={{ width, height }}
    >
      {!rendered && <Skeleton className="absolute inset-0 rounded-none" />}
      <canvas ref={canvasRef} className="absolute inset-0 select-none" />
      {markRects.length > 0 && (
        <div className="pointer-events-none absolute inset-0 opacity-25">
          {markRects.map((m, i) => (
            <div
              key={i}
              className={m.kind === 'evidence' ? 'pdf-mark-ev' : 'pdf-mark-tr'}
              style={{ position: 'absolute', top: m.t, left: m.l, width: m.w, height: m.h }}
            />
          ))}
        </div>
      )}
      <div ref={textRef} className="pdf-text-layer absolute inset-0" />
    </div>
  )
}

/** Replaces native ::selection painting: merges the selection's client rects
 * into one clean band per text line, so fragmented spans (math, scripts)
 * don't produce overlapping, misaligned highlight boxes. */
function SelectionOverlay({ hostRef }: { hostRef: React.RefObject<HTMLDivElement | null> }) {
  const [bands, setBands] = useState<{ t: number; l: number; w: number; h: number }[]>([])

  useEffect(() => {
    let raf = 0
    const recompute = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const host = hostRef.current
        const sel = window.getSelection()
        if (!host || !sel || sel.isCollapsed || sel.rangeCount === 0) {
          setBands([])
          return
        }
        const range = sel.getRangeAt(0)
        if (!host.contains(range.commonAncestorContainer)) {
          setBands([])
          return
        }
        // Compute rects per selected span over its *whitespace-trimmed* text:
        // PDF.js stretches trailing space glyphs across justification gaps,
        // so the browser's own rects bleed past the visible line ends.
        const rects = selectedPdfTextClientRects(host, range)
        setBands(clientRectsToLineBands(rects, host))
      })
    }
    document.addEventListener('selectionchange', recompute)
    return () => {
      document.removeEventListener('selectionchange', recompute)
      cancelAnimationFrame(raf)
    }
  }, [hostRef])

  if (!bands.length) return null
  return (
    <div className="pointer-events-none absolute inset-0 opacity-30">
      {bands.map((b, i) => (
        <div
          key={i}
          className="pdf-selection-band"
          style={{ top: b.t, left: b.l, width: b.w, height: b.h }}
        />
      ))}
    </div>
  )
}

export function PdfViewer({ url, pageTextRef, marks }: PdfViewerProps) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [error, setError] = useState<string | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(760)
  const { jumpPage } = useWorkbench()

  const marksByPage = useMemo(() => {
    const byPage = new Map<number, Mark[]>()
    const push = (page: number | null, mark: Mark) => {
      if (page == null) return
      const list = byPage.get(page) ?? []
      list.push(mark)
      byPage.set(page, list)
    }
    marks?.evidence.forEach((e) =>
      push(e.page, { kind: 'evidence', text: e.text, nodeId: e.node_id }),
    )
    marks?.translations.forEach((t) => push(t.page, { kind: 'translate', text: t.text }))
    return byPage
  }, [marks])

  useEffect(() => {
    if (!jumpPage) return
    wrapRef.current
      ?.querySelector(`[data-page="${jumpPage.page}"]`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [jumpPage])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => setWidth(Math.min(el.clientWidth - 48, 880))
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const [renderedUrl, setRenderedUrl] = useState(url)

  // Reset document state when the source url changes (render-time adjustment).
  if (renderedUrl !== url) {
    setRenderedUrl(url)
    setDoc(null)
    setError(null)
  }

  useEffect(() => {
    let cancelled = false
    pageTextRef.current.clear()
    const task = pdfjs.getDocument({ url })
    task.promise.then(
      (d) => !cancelled && setDoc(d),
      (e) => !cancelled && setError(String(e?.message ?? e)),
    )
    return () => {
      cancelled = true
      task.destroy().catch(() => {})
    }
  }, [url, pageTextRef])

  const innerRef = useRef<HTMLDivElement>(null)

  return (
    <div ref={wrapRef} className="h-full overflow-y-auto bg-surface-muted/60 px-6 py-6">
      {error && (
        <p className="mx-auto max-w-md py-16 text-center text-sm text-danger">
          Could not load the PDF: {error}
        </p>
      )}
      {!doc && !error && (
        <div className="mx-auto space-y-4" style={{ width }}>
          <Skeleton className="h-[1000px] rounded-none" />
        </div>
      )}
      {doc && (
        <div ref={innerRef} className="relative">
          {Array.from({ length: doc.numPages }, (_, i) => (
            <PdfPage
              key={i + 1}
              doc={doc}
              pageNumber={i + 1}
              width={width}
              pageTextRef={pageTextRef}
              marks={marksByPage.get(i + 1) ?? []}
            />
          ))}
          <SelectionOverlay hostRef={innerRef} />
        </div>
      )}
    </div>
  )
}
