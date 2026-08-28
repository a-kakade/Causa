import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function SectionHeading({
  eyebrow,
  title,
  action,
  className,
}: {
  eyebrow?: string
  title: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-end justify-between gap-3', className)}>
      <div>
        {eyebrow ? <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">{eyebrow}</p> : null}
        <h2 className="text-sm font-semibold text-(--color-ink)">{title}</h2>
      </div>
      {action}
    </div>
  )
}
