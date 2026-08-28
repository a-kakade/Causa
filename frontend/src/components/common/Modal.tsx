import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

export function Modal({
  open,
  onOpenChange,
  title,
  children,
  footer,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-(--color-ink)/25" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[480px] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 rounded-(--radius-lg) border border-(--color-border) bg-(--color-surface) shadow-(--shadow-md) focus:outline-none">
          <div className="flex items-center justify-between gap-3 border-b border-(--color-border) px-5 py-3.5">
            <Dialog.Title className="text-sm font-semibold text-(--color-ink)">{title}</Dialog.Title>
            <Dialog.Close className="rounded-(--radius-sm) p-1 text-(--color-ink-faint) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="px-5 py-4">{children}</div>
          {footer ? <div className="flex justify-end gap-2 border-t border-(--color-border) px-5 py-3.5">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
