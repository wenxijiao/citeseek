import { Languages, Quote } from 'lucide-react'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'
import { EvidencePanel } from '@/components/evidence/EvidencePanel'
import { TranslatePanel } from '@/components/dialogs/TranslatePanel'

const TABS = [
  { id: 'evidence' as const, label: 'Evidence', icon: Quote },
  { id: 'translate' as const, label: 'Translate', icon: Languages },
]

export function RightPanel() {
  const { rightTab, setRightTab } = useWorkbench()
  return (
    <div className="flex h-full flex-col">
      <nav className="flex shrink-0 gap-1 border-b border-border px-2 pt-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setRightTab(id)}
            className={cn(
              'flex items-center gap-1.5 rounded-t-lg border-b-2 px-3 py-2 text-xs font-medium transition-colors',
              rightTab === id
                ? 'border-accent text-accent'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1">
        {rightTab === 'evidence' ? <EvidencePanel /> : <TranslatePanel />}
      </div>
    </div>
  )
}
