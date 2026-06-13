import { MessagesSquare, Network } from 'lucide-react'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { TreeSidebar } from '@/components/tree/TreeSidebar'
import { ClaimInput } from './ClaimInput'

const TABS = [
  { id: 'discuss' as const, label: 'Discuss', icon: MessagesSquare },
  { id: 'map' as const, label: 'Map', icon: Network },
]

export function LeftPanel() {
  const { leftTab, setLeftTab } = useWorkbench()
  return (
    <div className="flex h-full flex-col">
      <nav className="flex shrink-0 gap-1 border-b border-border px-2 pt-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setLeftTab(id)}
            className={cn(
              'flex items-center gap-1.5 rounded-t-lg border-b-2 px-3 py-2 text-xs font-medium transition-colors',
              leftTab === id
                ? 'border-accent text-accent'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </nav>
      {leftTab === 'discuss' ? (
        <div className="min-h-0 flex-1">
          <ChatPanel />
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1">
            <TreeSidebar />
          </div>
          <ClaimInput />
        </>
      )}
    </div>
  )
}
