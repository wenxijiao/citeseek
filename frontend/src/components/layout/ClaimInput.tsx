import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Loader2 } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'

/** Free-text claim input — starts a root query in the active session. */
export function ClaimInput({ hero = false }: { hero?: boolean }) {
  const [text, setText] = useState('')
  const { sessionId, setSession, setActiveNode } = useWorkbench()
  const queryClient = useQueryClient()

  const submit = useMutation({
    mutationFn: async () => {
      const claim = text.trim()
      if (!claim) throw new Error('empty')
      let sid = sessionId
      if (!sid) {
        const session = await api.createSession(claim.slice(0, 60))
        sid = session.id
        setSession(sid)
      }
      return api.startQuery({ session_id: sid, selected_text: claim })
    },
    onSuccess: ({ node_id }) => {
      setText('')
      setActiveNode(node_id)
      queryClient.invalidateQueries({ queryKey: ['tree'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!submit.isPending && text.trim()) submit.mutate()
    }
  }

  return (
    <div
      className={cn(
        'relative',
        hero ? 'w-full max-w-xl' : 'border-t border-border bg-surface p-2.5',
      )}
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={hero ? 3 : 2}
        placeholder={
          hero
            ? 'Paste a claim from a paper, e.g. “GANs train a generator and a discriminator through an adversarial process”…'
            : 'Ask about another claim…'
        }
        className={cn(
          'w-full resize-none rounded-xl border border-border bg-surface text-foreground',
          'placeholder:text-muted-foreground/70 focus:outline-2 focus:outline-accent',
          hero ? 'p-4 pr-12 text-[15px] leading-6 shadow-sm' : 'p-2.5 pr-10 text-[13px] leading-5',
        )}
      />
      <button
        onClick={() => submit.mutate()}
        disabled={submit.isPending || !text.trim()}
        title="Find supporting papers"
        className={cn(
          'absolute flex items-center justify-center rounded-lg bg-accent text-accent-foreground',
          'transition-opacity disabled:opacity-40',
          hero ? 'bottom-4 right-3 h-8 w-8' : 'bottom-[18px] right-[18px] h-6 w-6',
        )}
      >
        {submit.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ArrowUp className="h-4 w-4" />
        )}
      </button>
    </div>
  )
}
