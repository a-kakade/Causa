import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

export function Drawer({
  open,
  onOpenChange,
  title,
  subtitle,
  children,
  width = 'md',
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  width?: 'sm' | 'md' | 'lg'
}) {
  const widthClass = width === 'lg' ? 'w-[560px]' : width === 'sm' ? 'w-[380px]' : 'w-[460px]'
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-(--color-ink)/25 data-[state=open]:animate-in data-[state=open]:fade-in" />
        <Dialog.Content
          className={`fixed inset-y-0 right-0 z-50 flex ${widthClass} max-w-full flex-col border-l border-(--color-border) bg-(--color-surface) shadow-(--shadow-md) focus:outline-none`}
        >
          <div className="flex items-start justify-between gap-3 border-b border-(--color-border) px-5 py-4">
            <div>
              <Dialog.Title className="text-sm font-semibold text-(--color-ink)">{title}</Dialog.Title>
              {subtitle ? <Dialog.Description className="mt-0.5 text-xs text-(--color-ink-muted)">{subtitle}</Dialog.Description> : null}
            </div>
            <Dialog.Close className="rounded-(--radius-sm) p-1 text-(--color-ink-faint) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="scrollbar-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
