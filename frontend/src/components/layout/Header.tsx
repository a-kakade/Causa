import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Bell, ChevronDown, Search } from 'lucide-react'
import { useAppState } from '@/state/AppStateContext'
import type { RequesterRole } from '@/types/common'
import { StatusDot } from '@/components/common/StatusDot'

const ROLES: { value: RequesterRole; label: string; clearance: string }[] = [
  { value: 'EXECUTIVE', label: 'Executive', clearance: 'PUBLIC_ANALYTICAL' },
  { value: 'ANALYST', label: 'Analyst', clearance: 'INTERNAL' },
  { value: 'INTERNAL', label: 'Internal (audit)', clearance: 'RESTRICTED' },
]

export function Header() {
  const { requesterRole, setRequesterRole } = useAppState()
  const role = ROLES.find((r) => r.value === requesterRole)!

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-(--color-border) bg-(--color-surface) px-4">
      <div className="flex items-center gap-4 text-[13px]">
        <div>
          <span className="text-(--color-ink-faint)">Workspace</span>{' '}
          <span className="font-medium text-(--color-ink)">Revenue Intelligence</span>
        </div>
        <div className="h-4 w-px bg-(--color-border)" />
        <div>
          <span className="text-(--color-ink-faint)">Period</span>{' '}
          <span className="font-medium text-(--color-ink)">November 2017</span>
        </div>
        <div className="h-4 w-px bg-(--color-border)" />
        <div className="flex items-center gap-1.5">
          <StatusDot tone="positive" />
          <span className="text-(--color-ink-muted)">Fixtures current</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="rounded-(--radius-sm) p-1.5 text-(--color-ink-faint) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)"
          aria-label="Search"
        >
          <Search className="size-4" />
        </button>
        <button
          type="button"
          className="rounded-(--radius-sm) p-1.5 text-(--color-ink-faint) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)"
          aria-label="Notifications"
        >
          <Bell className="size-4" />
        </button>
        <div className="h-4 w-px bg-(--color-border)" />

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button type="button" className="flex items-center gap-2 rounded-(--radius-sm) py-1 pl-1 pr-2 hover:bg-(--color-surface-2)">
              <div className="flex size-6 items-center justify-center rounded-full bg-(--color-accent-soft) text-[11px] font-bold text-(--color-accent-strong)">
                {role.label[0]}
              </div>
              <div className="text-left leading-tight">
                <div className="text-[12px] font-medium text-(--color-ink)">{role.label}</div>
                <div className="text-[10px] text-(--color-ink-faint)">{role.clearance}</div>
              </div>
              <ChevronDown className="size-3 text-(--color-ink-faint)" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={8}
              className="z-50 w-64 rounded-(--radius-md) border border-(--color-border) bg-(--color-surface) p-1 shadow-(--shadow-md)"
            >
              <p className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">
                Switch requester role (RBAC demo)
              </p>
              {ROLES.map((r) => (
                <DropdownMenu.Item
                  key={r.value}
                  onSelect={() => setRequesterRole(r.value)}
                  className="flex cursor-pointer items-center justify-between rounded-(--radius-sm) px-2.5 py-1.5 text-[13px] text-(--color-ink) outline-none data-[highlighted]:bg-(--color-surface-2)"
                >
                  <span>{r.label}</span>
                  <span className="text-[10px] font-mono text-(--color-ink-faint)">{r.clearance}</span>
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </header>
  )
}
