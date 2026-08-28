import { AlertTriangle } from 'lucide-react'

export function ErrorState({ title = 'Something went wrong', message }: { title?: string; message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-(--radius-md) border border-(--color-negative-soft) bg-(--color-negative-soft) px-6 py-10 text-center">
      <AlertTriangle className="size-5 text-(--color-negative)" strokeWidth={1.75} />
      <p className="text-sm font-semibold text-(--color-negative)">{title}</p>
      {message ? <p className="max-w-sm text-xs text-(--color-ink-muted)">{message}</p> : null}
    </div>
  )
}
