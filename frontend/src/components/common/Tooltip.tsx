import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={800} skipDelayDuration={300}>
      {children}
    </TooltipPrimitive.Provider>
  )
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-ink) px-2.5 py-1.5 text-xs text-(--color-ink-inverse) shadow-(--shadow-md) data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in data-[state=delayed-open]:duration-150"
        >
          {content}
          <TooltipPrimitive.Arrow className="fill-(--color-ink)" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
