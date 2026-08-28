import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-(--radius-lg) border border-(--color-border) bg-(--color-surface) shadow-(--shadow-xs)', className)}
      {...rest}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  icon?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-start justify-between gap-3 border-b border-(--color-border) px-4 py-3', className)}>
      <div className="flex items-start gap-2.5">
        {icon}
        <div>
          <h3 className="text-[13px] font-semibold tracking-wide text-(--color-ink)">{title}</h3>
          {subtitle ? <p className="mt-0.5 text-xs text-(--color-ink-muted)">{subtitle}</p> : null}
        </div>
      </div>
      {action}
    </div>
  )
}

export function CardBody({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('px-4 py-3.5', className)} {...rest}>
      {children}
    </div>
  )
}
