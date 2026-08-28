import type { LucideIcon } from 'lucide-react'
import { Inbox } from 'lucide-react'
import type { ReactNode } from 'react'

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-(--radius-md) border border-dashed border-(--color-border-strong) px-6 py-10 text-center">
      <Icon className="size-5 text-(--color-ink-faint)" strokeWidth={1.5} />
      <p className="text-sm font-medium text-(--color-ink-muted)">{title}</p>
      {description ? <p className="max-w-sm text-xs text-(--color-ink-faint)">{description}</p> : null}
      {action}
    </div>
  )
}
