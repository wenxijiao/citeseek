import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { Button } from '@/components/ui/primitives'

const PROVIDERS = ['anthropic', 'openai', 'gemini', 'deepseek', 'ollama']

export function SettingsDialog() {
  const { settingsOpen, setSettingsOpen } = useWorkbench()
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
    enabled: settingsOpen,
  })
  const [form, setForm] = useState<Record<string, string>>({})
  const [loadedSettings, setLoadedSettings] = useState<Record<string, string> | undefined>()

  // Adopt freshly fetched settings into the form (render-time state adjustment).
  if (settings.data && settings.data !== loadedSettings) {
    setLoadedSettings(settings.data)
    setForm(settings.data)
  }

  const save = useMutation({
    mutationFn: () => api.updateSettings(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      setSettingsOpen(false)
    },
  })

  if (!settingsOpen) return null

  const field = (key: string) => ({
    value: form[key] ?? '',
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value })),
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 animate-fade-in"
      onClick={() => setSettingsOpen(false)}
    >
      <div
        className="w-full max-w-md rounded-xl border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold">Settings</h2>
          <Button size="icon" variant="ghost" onClick={() => setSettingsOpen(false)}>
            <X className="h-4 w-4" />
          </Button>
        </header>
        <div className="space-y-4 px-5 py-4">
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">LLM provider</span>
            <select
              {...field('llm.provider')}
              className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2.5 text-sm"
            >
              <option value="">(from environment)</option>
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">
              Model (blank = provider default)
            </span>
            <input
              {...field('llm.model')}
              placeholder="e.g. claude-opus-4-8"
              className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2.5 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">Translation language</span>
            <input
              {...field('translate.target_lang')}
              placeholder="Chinese"
              className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-2.5 text-sm"
            />
          </label>
          <p className="text-[11px] leading-4 text-muted-foreground">
            API keys are read from the server’s <code>.env</code> file
            (ANTHROPIC_API_KEY, OPENAI_API_KEY, …). The provider chosen here selects which
            key is used.
          </p>
        </div>
        <footer className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="outline" size="sm" onClick={() => setSettingsOpen(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            Save
          </Button>
        </footer>
      </div>
    </div>
  )
}
