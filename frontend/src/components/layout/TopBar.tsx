import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Moon, Plus, Settings2, Sun, Trash2 } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/primitives'

function SessionSwitcher() {
  const { sessionId, setSession } = useWorkbench()
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.listSessions })

  const deleteSession = useMutation({
    mutationFn: (id: string) => api.deleteSession(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (id === sessionId) setSession(null)
    },
  })

  const current = sessions.data?.find((s) => s.id === sessionId)
  const label = (s: { title: string | null; root_paper_title: string | null; id: string }) =>
    s.root_paper_title || s.title || `Session ${s.id.slice(0, 8)}`

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 max-w-72 items-center gap-1.5 rounded-lg border border-border px-2.5 text-sm hover:bg-surface-muted"
      >
        <span className="truncate">{current ? label(current) : 'Select session'}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-9 z-40 w-80 overflow-hidden rounded-xl border border-border bg-surface shadow-xl animate-fade-in">
            <div className="max-h-72 overflow-y-auto p-1.5">
              {sessions.data?.map((session) => (
                <div
                  key={session.id}
                  className={cn(
                    'group flex w-full items-center rounded-lg hover:bg-surface-muted',
                    session.id === sessionId && 'bg-accent-soft',
                  )}
                >
                  <button
                    onClick={() => {
                      setSession(session.id)
                      setOpen(false)
                    }}
                    className="min-w-0 flex-1 px-2.5 py-2 text-left"
                  >
                    <span className="block truncate text-[13px]">{label(session)}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {session.node_count} queries · {session.updated_at}
                    </span>
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      if (confirm(`Delete “${label(session)}” and its exploration history?`))
                        deleteSession.mutate(session.id)
                    }}
                    title="Delete session"
                    className="mr-1.5 rounded-md p-1.5 text-muted-foreground/50 opacity-0 transition-opacity hover:bg-danger/10 hover:text-danger group-hover:opacity-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
              {sessions.data?.length === 0 && (
                <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                  No sessions yet.
                </p>
              )}
            </div>
            <div className="border-t border-border p-1.5">
              <button
                onClick={() => {
                  setSession(null)
                  setOpen(false)
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-medium text-accent hover:bg-accent-soft"
              >
                <Plus className="h-3.5 w-3.5" /> New session (upload a paper)
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export function TopBar() {
  const { theme, toggle } = useTheme()
  const { setSettingsOpen } = useWorkbench()
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-3.5">
      <div className="flex items-center gap-2">
        <div className="brand-gradient flex h-6 w-6 items-center justify-center rounded-md shadow-sm">
          <span className="font-serif text-[13px] font-bold italic text-white">C</span>
        </div>
        <span className="font-serif text-[15px] font-semibold tracking-tight">CiteSeek</span>
      </div>
      <div className="ml-2">
        <SessionSwitcher />
      </div>
      <div className="ml-auto flex items-center gap-1">
        <Button size="icon" variant="ghost" onClick={toggle} title="Toggle theme">
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
        <Button size="icon" variant="ghost" onClick={() => setSettingsOpen(true)} title="Settings">
          <Settings2 className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
