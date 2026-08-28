import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

type Tone = 'neutral' | 'accent' | 'positive' | 'negative' | 'warning' | 'abstain'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-(--color-neutral-soft) text-(--color-ink-muted)',
  accent: 'bg-(--color-accent-soft) text-(--color-accent-strong)',
  positive: 'bg-(--color-positive-soft) text-(--color-positive)',
  negative: 'bg-(--color-negative-soft) text-(--color-negative)',
  warning: 'bg-(--color-warning-soft) text-(--color-warning)',
  abstain: 'bg-(--color-confidence-abstain-soft) text-(--color-confidence-abstain)',
}

export function Badge({
  children,
  tone = 'neutral',
  className,
  icon,
}: {
  children: ReactNode
  tone?: Tone
  className?: string
  icon?: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-(--radius-xs) px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide',
        TONE_CLASSES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}
