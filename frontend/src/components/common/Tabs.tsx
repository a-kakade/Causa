import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cn } from '@/lib/cn'

export const Tabs = TabsPrimitive.Root

export function TabsList({ className, ...rest }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn('inline-flex items-center gap-1 rounded-(--radius-md) border border-(--color-border) bg-(--color-surface-2) p-0.5', className)}
      {...rest}
    />
  )
}

export function TabsTrigger({ className, ...rest }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'rounded-(--radius-sm) px-3 py-1.5 text-[13px] font-medium text-(--color-ink-muted) transition-colors duration-150',
        'hover:text-(--color-ink) data-[state=active]:bg-(--color-surface) data-[state=active]:text-(--color-ink) data-[state=active]:shadow-(--shadow-xs)',
        className,
      )}
      {...rest}
    />
  )
}

export const TabsContent = TabsPrimitive.Content
