import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Loader2, MessagesSquare, X } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'

function QuoteChip({ quote, onClear }: { quote: string; onClear?: () => void }) {
  return (
    <div className="flex items-start gap-1.5 rounded-lg border-l-2 border-accent bg-accent-soft/60 px-2.5 py-1.5">
      <p className="line-clamp-3 flex-1 font-serif text-[11px] italic leading-4 text-foreground/80">
        “{quote}”
      </p>
      {onClear && (
        <button onClick={onClear} className="shrink-0 text-muted-foreground hover:text-foreground">
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

export function ChatPanel() {
  const { sessionId, openPaperId, pendingQuote, setPendingQuote } = useWorkbench()
  const [text, setText] = useState('')
  // What's in flight, shown as an optimistic bubble while the LLM responds.
  const [inFlight, setInFlight] = useState<{ message: string; quote: string | null } | null>(null)
  const queryClient = useQueryClient()
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const chat = useQuery({
    queryKey: ['chat', sessionId],
    queryFn: () => api.listChat(sessionId!),
    enabled: !!sessionId,
  })

  const send = useMutation({
    mutationFn: (payload: { message: string; quote: string | null }) =>
      api.sendChat(sessionId!, { ...payload, paper_id: openPaperId }),
    onSuccess: () => {
      setInFlight(null)
      queryClient.invalidateQueries({ queryKey: ['chat', sessionId] })
    },
    onError: () => {
      // put the message back so the user can retry
      if (inFlight) {
        setText(inFlight.message)
        setPendingQuote(inFlight.quote)
      }
      setInFlight(null)
    },
  })

  const submit = () => {
    const message = text.trim()
    if (!message || send.isPending) return
    setInFlight({ message, quote: pendingQuote })
    setText('')
    setPendingQuote(null)
    send.mutate({ message, quote: pendingQuote })
  }

  // keep scrolled to the latest message
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [chat.data?.messages.length, send.isPending])

  // focus the input when a quote arrives from the reader
  useEffect(() => {
    if (pendingQuote) inputRef.current?.focus()
  }, [pendingQuote])

  const messages = chat.data?.messages ?? []

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !send.isPending && (
          <div className="px-2 py-8 text-center">
            <MessagesSquare className="mx-auto h-5 w-5 text-muted-foreground/50" />
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Discuss this paper with the assistant — ask about anything you don’t
              understand, or select a passage and choose <em>Discuss</em>.
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={cn('space-y-1', msg.role === 'user' && 'pl-6')}>
            {msg.quote && <QuoteChip quote={msg.quote} />}
            <div
              className={cn(
                'rounded-xl px-3 py-2 text-[13px] leading-6 whitespace-pre-wrap',
                msg.role === 'user'
                  ? 'bg-accent text-accent-foreground'
                  : 'bg-surface-muted text-foreground',
              )}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {send.isPending && inFlight && (
          <div className="space-y-1">
            <div className="pl-6">
              {inFlight.quote && <QuoteChip quote={inFlight.quote} />}
              <div className="mt-1 rounded-xl bg-accent px-3 py-2 text-[13px] leading-6 text-accent-foreground whitespace-pre-wrap">
                {inFlight.message}
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-xl bg-surface-muted px-3 py-2.5 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Thinking…
            </div>
          </div>
        )}
        {send.isError && (
          <p className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
            {(send.error as Error).message.includes('409')
              ? 'Discussion needs an LLM provider — add an API key in Settings.'
              : 'Failed to send. Try again.'}
          </p>
        )}
      </div>

      <div className="border-t border-border bg-surface p-2.5">
        {pendingQuote && (
          <div className="mb-2">
            <QuoteChip quote={pendingQuote} onClear={() => setPendingQuote(null)} />
          </div>
        )}
        <div className="relative">
          <textarea
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            rows={2}
            placeholder={pendingQuote ? 'Ask about this passage…' : 'Ask about the paper…'}
            className="w-full resize-none rounded-xl border border-border bg-surface p-2.5 pr-10 text-[13px] leading-5 placeholder:text-muted-foreground/70 focus:outline-2 focus:outline-accent"
          />
          <button
            onClick={submit}
            disabled={send.isPending || !text.trim()}
            className="absolute bottom-[14px] right-2.5 flex h-6 w-6 items-center justify-center rounded-lg bg-accent text-accent-foreground disabled:opacity-40"
          >
            {send.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ArrowUp className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
