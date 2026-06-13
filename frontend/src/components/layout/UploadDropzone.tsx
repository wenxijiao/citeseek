import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUp, Loader2 } from 'lucide-react'
import { api } from '@/api/client'
import { useWorkbench } from '@/stores/workbench'
import { cn } from '@/lib/utils'

/** Hero dropzone: upload the paper you want to read; it becomes the session. */
export function UploadDropzone() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const { setSession, openPaper } = useWorkbench()
  const queryClient = useQueryClient()

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadSession(file),
    onSuccess: ({ session, paper_id }) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      setSession(session.id)
      openPaper(paper_id)
    },
  })

  const onFile = (file: File | undefined | null) => {
    if (file && file.type === 'application/pdf' && !upload.isPending) upload.mutate(file)
  }

  return (
    <button
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        onFile(e.dataTransfer.files[0])
      }}
      disabled={upload.isPending}
      className={cn(
        'group w-full rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
        dragOver
          ? 'border-accent bg-accent-soft'
          : 'border-border bg-surface hover:border-accent/60 hover:bg-accent-soft/40',
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0])}
      />
      {upload.isPending ? (
        <>
          <Loader2 className="mx-auto h-6 w-6 animate-spin text-accent" />
          <p className="mt-3 text-sm font-medium">Parsing your paper…</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Extracting text and building the passage index
          </p>
        </>
      ) : (
        <>
          <FileUp className="mx-auto h-6 w-6 text-muted-foreground transition-colors group-hover:text-accent" />
          <p className="mt-3 text-sm font-medium">
            Drop the paper you want to read <span className="text-muted-foreground">(PDF)</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            or click to browse — it opens in the reader and becomes this session
          </p>
        </>
      )}
      {upload.isError && (
        <p className="mt-3 text-xs text-danger">
          Could not parse that PDF — try another file.
        </p>
      )}
    </button>
  )
}
