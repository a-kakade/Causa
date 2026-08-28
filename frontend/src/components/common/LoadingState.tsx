export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-2 py-6 text-xs text-(--color-ink-faint)">
      <span className="size-3 animate-spin rounded-full border-2 border-(--color-border-strong) border-t-(--color-accent)" />
      {label}…
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-(--radius-sm) bg-(--color-surface-2) ${className ?? ''}`} />
}
