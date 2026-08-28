import { cn } from '@/lib/cn'

export function StatusDot({ tone = 'positive', pulse = false, className }: { tone?: 'positive' | 'warning' | 'negative' | 'neutral' | 'accent'; pulse?: boolean; className?: string }) {
  const color =
    tone === 'positive'
      ? 'bg-(--color-positive)'
      : tone === 'warning'
        ? 'bg-(--color-warning)'
        : tone === 'negative'
          ? 'bg-(--color-negative)'
          : tone === 'accent'
            ? 'bg-(--color-accent)'
            : 'bg-(--color-neutral)'
  return (
    <span className={cn('relative inline-flex size-1.5', className)}>
      {pulse ? <span className={cn('absolute inline-flex size-full animate-ping rounded-full opacity-60', color)} /> : null}
      <span className={cn('relative inline-flex size-1.5 rounded-full', color)} />
    </span>
  )
}
