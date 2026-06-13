export interface OverlayBand {
  t: number
  l: number
  w: number
  h: number
}

export interface ViewportRect {
  top: number
  left: number
  width: number
  height: number
}

export interface TextClientRect extends ViewportRect {
  right: number
  bottom: number
}

const MAX_WORD_GAP_PX = 28

function verticalOverlap(a: { top: number; bottom: number }, b: TextClientRect): number {
  return Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
}

let measureContext: CanvasRenderingContext2D | null = null

function getMeasureContext(): CanvasRenderingContext2D | null {
  if (measureContext) return measureContext
  const canvas = document.createElement('canvas')
  measureContext = canvas.getContext('2d')
  return measureContext
}

function fontForElement(el: HTMLElement): string {
  const style = getComputedStyle(el)
  return [
    style.fontStyle,
    style.fontVariant,
    style.fontWeight,
    style.fontSize,
    style.fontFamily,
  ].join(' ')
}

function textWidth(el: HTMLElement, text: string): number {
  const ctx = getMeasureContext()
  if (!ctx) return text.length
  ctx.font = fontForElement(el)
  return ctx.measureText(text).width
}

function measuredTextRect(
  span: HTMLElement,
  text: string,
  start: number,
  end: number,
): TextClientRect | null {
  const spanRect = span.getBoundingClientRect()
  if (spanRect.width <= 1 || spanRect.height <= 1 || spanRect.height >= 80) return null

  const fullWidth = textWidth(span, text)
  if (fullWidth <= 0) return null

  const leftWidth = textWidth(span, text.slice(0, start))
  const rightWidth = textWidth(span, text.slice(0, end))
  const scale = spanRect.width / fullWidth
  const left = spanRect.left + leftWidth * scale
  const right = spanRect.left + rightWidth * scale
  const width = right - left
  if (width <= 1) return null

  return {
    top: spanRect.top,
    bottom: spanRect.bottom,
    left,
    right,
    width,
    height: spanRect.height,
  }
}

export function visibleWordClientRects(
  span: HTMLElement,
  node: ChildNode,
  start: number,
  end: number,
): TextClientRect[] {
  if (node.nodeType !== Node.TEXT_NODE) return []
  const text = node.textContent ?? ''
  let from = Math.max(0, Math.min(start, text.length))
  let to = Math.max(from, Math.min(end, text.length))
  while (to > from && /\s/.test(text[to - 1])) to--
  while (from < to && /\s/.test(text[from])) from++
  if (from >= to) return []

  const rects: TextClientRect[] = []
  const selected = text.slice(from, to)
  const words = /\S+/g
  let match: RegExpExecArray | null
  while ((match = words.exec(selected))) {
    const wordStart = from + match.index
    const wordEnd = wordStart + match[0].length
    const rect = measuredTextRect(span, text, wordStart, wordEnd)
    if (rect) rects.push(rect)
  }
  return rects
}

interface ColumnBounds {
  left: number
  right: number
}

/** Estimate the text column extent of one page layer from its normal spans.
 *  Equation fragments and broken-metric spans can sit visually outside the
 *  column; selection rects are clipped against these bounds so they cannot
 *  produce stray highlight bands in the margins. */
function layerColumnBounds(layer: HTMLElement): ColumnBounds | null {
  const lefts: number[] = []
  const rights: number[] = []
  for (const sp of layer.querySelectorAll<HTMLElement>('span')) {
    if ((sp.textContent ?? '').trim().length < 2) continue
    const r = sp.getBoundingClientRect()
    if (r.height <= 1 || r.height >= 40 || r.width <= 8) continue
    lefts.push(r.left)
    rights.push(r.right)
  }
  if (rights.length < 8) return null
  lefts.sort((a, b) => a - b)
  rights.sort((a, b) => a - b)
  const at = (arr: number[], p: number) => arr[Math.min(arr.length - 1, Math.floor(arr.length * p))]
  return { left: at(lefts, 0.05) - 4, right: at(rights, 0.95) + 4 }
}

function clipToColumn(rect: TextClientRect, bounds: ColumnBounds | null): TextClientRect | null {
  if (!bounds) return rect
  const left = Math.max(rect.left, bounds.left)
  const right = Math.min(rect.right, bounds.right)
  if (right - left <= 1) return null
  return { ...rect, left, right, width: right - left }
}

export function selectedPdfTextClientRects(root: HTMLElement, range: Range): TextClientRect[] {
  const rects: TextClientRect[] = []
  const boundsByLayer = new Map<HTMLElement, ColumnBounds | null>()
  for (const sp of root.querySelectorAll<HTMLElement>('.pdf-text-layer span')) {
    if (!range.intersectsNode(sp)) continue
    const tn = sp.firstChild
    if (!tn || tn.nodeType !== Node.TEXT_NODE) continue
    const layer = sp.closest<HTMLElement>('.pdf-text-layer')
    let bounds: ColumnBounds | null = null
    if (layer) {
      if (!boundsByLayer.has(layer)) boundsByLayer.set(layer, layerColumnBounds(layer))
      bounds = boundsByLayer.get(layer) ?? null
    }
    const text = tn.textContent ?? ''
    const start = range.startContainer === tn ? range.startOffset : 0
    const end = range.endContainer === tn ? range.endOffset : text.length
    for (const rect of visibleWordClientRects(sp, tn, start, end)) {
      const clipped = clipToColumn(rect, bounds)
      if (clipped) rects.push(clipped)
    }
  }
  return rects
}

export function clientRectsToLineBands(rects: TextClientRect[], host: HTMLElement): OverlayBand[] {
  const hostRect = host.getBoundingClientRect()
  const rows: { top: number; bottom: number; rects: TextClientRect[] }[] = []

  for (const r of [...rects].sort((a, b) => a.top - b.top || a.left - b.left)) {
    const row = rows.find((candidate) => {
      const overlap = verticalOverlap(candidate, r)
      return overlap > Math.min(candidate.bottom - candidate.top, r.height) * 0.45
    })
    if (row) {
      row.top = Math.min(row.top, r.top)
      row.bottom = Math.max(row.bottom, r.bottom)
      row.rects.push(r)
    } else {
      rows.push({ top: r.top, bottom: r.bottom, rects: [r] })
    }
  }

  const bands: OverlayBand[] = []
  for (const row of rows) {
    const sorted = row.rects.sort((a, b) => a.left - b.left)
    let segment: { left: number; right: number } | null = null
    const flush = () => {
      if (!segment) return
      const top = Math.max(row.top, hostRect.top)
      const bottom = Math.min(row.bottom, hostRect.bottom)
      const left = Math.max(segment.left, hostRect.left)
      const right = Math.min(segment.right, hostRect.right)
      if (right - left > 1 && bottom - top > 1) {
        bands.push({
          t: top - hostRect.top,
          l: left - hostRect.left,
          w: right - left,
          h: bottom - top,
        })
      }
      segment = null
    }

    for (const r of sorted) {
      if (!segment) {
        segment = { left: r.left, right: r.right }
      } else if (r.left - segment.right <= MAX_WORD_GAP_PX) {
        segment.right = Math.max(segment.right, r.right)
      } else {
        flush()
        segment = { left: r.left, right: r.right }
      }
    }
    flush()
  }
  return bands
}

export function boundingViewportRect(rects: TextClientRect[]): ViewportRect | null {
  if (!rects.length) return null
  const top = Math.min(...rects.map((r) => r.top))
  const left = Math.min(...rects.map((r) => r.left))
  const right = Math.max(...rects.map((r) => r.right))
  const bottom = Math.max(...rects.map((r) => r.bottom))
  return { top, left, width: right - left, height: bottom - top }
}
