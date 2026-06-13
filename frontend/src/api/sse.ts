import { fetchEventSource } from '@microsoft/fetch-event-source'
import type { StageEventPayload } from './types'

export interface NodeStreamHandlers {
  onStage: (event: StageEventPayload) => void
  onDone: () => void
  onError: (message: string) => void
}

/** Subscribe to a node's pipeline progress. Returns an abort function. */
export function streamNode(nodeId: string, handlers: NodeStreamHandlers): () => void {
  const controller = new AbortController()
  fetchEventSource(`/api/nodes/${nodeId}/stream`, {
    signal: controller.signal,
    openWhenHidden: true,
    onmessage(msg) {
      if (!msg.data) return
      let payload: StageEventPayload
      try {
        payload = JSON.parse(msg.data)
      } catch {
        return
      }
      if (msg.event === 'done') {
        handlers.onStage(payload)
        handlers.onDone()
        controller.abort()
      } else if (msg.event === 'error') {
        handlers.onError(payload.detail ?? payload.error?.toString() ?? 'pipeline failed')
        controller.abort()
      } else {
        handlers.onStage(payload)
      }
    },
    onerror(err) {
      handlers.onError(String(err))
      controller.abort()
      throw err
    },
  }).catch(() => {
    /* aborted */
  })
  return () => controller.abort()
}
