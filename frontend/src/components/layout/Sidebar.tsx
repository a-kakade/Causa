import {
  Activity,
  Database,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  Microscope,
  ScrollText,
  Shield,
  TrendingUp,
  Waypoints,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/cn'

interface NavItem {
  label: string
  to: string
  icon?: LucideIcon
  end?: boolean
}
interface NavGroup {
  label?: string
  items: NavItem[]
}

const GROUPS: NavGroup[] = [
  { items: [{ label: 'Overview', to: '/overview', icon: LayoutDashboard }] },
  {
    label: 'Investigations',
    items: [
      { label: 'Active', to: '/investigate/revenue', icon: Microscope },
      { label: 'History', to: '/investigate', icon: ScrollText, end: true },
      { label: 'Process Trace', to: '/investigate/revenue?tab=process', icon: Waypoints },
    ],
  },
  {
    label: 'Evidence',
    items: [
      { label: 'Explorer', to: '/evidence', icon: Database, end: true },
      { label: 'Evidence Graph', to: '/evidence?tab=graph', icon: GitBranch },
    ],
  },
  { label: 'Decisions', items: [{ label: 'Recommendations', to: '/decisions', icon: ListChecks }] },
  { label: 'Outcomes', items: [{ label: 'Impact & Feedback', to: '/outcomes', icon: TrendingUp }] },
  {
    label: 'System',
    items: [
      { label: 'Audit Logs', to: '/logs', icon: ScrollText },
      { label: 'Security', to: '/security', icon: Shield },
      { label: 'Telemetry', to: '/telemetry', icon: Activity },
    ],
  },
]

export function Sidebar() {
  return (
    <aside className="flex h-full w-[212px] shrink-0 flex-col border-r border-(--color-border) bg-(--color-surface)">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex size-6 items-center justify-center rounded-(--radius-sm) bg-(--color-accent) text-[11px] font-bold text-(--color-ink-inverse)">
          C
        </div>
        <span className="text-[13px] font-bold tracking-tight text-(--color-ink)">CAUSA</span>
      </div>
      <nav className="scrollbar-thin flex-1 overflow-y-auto px-2.5 pb-4">
        {GROUPS.map((group, gi) => (
          <div key={group.label ?? gi} className={gi > 0 ? 'mt-4' : ''}>
            {group.label ? (
              <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">{group.label}</p>
            ) : null}
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2 rounded-(--radius-sm) px-2 py-1.5 text-[13px] font-medium transition-colors duration-100',
                        isActive
                          ? 'bg-(--color-accent-soft) text-(--color-accent-strong)'
                          : 'text-(--color-ink-muted) hover:bg-(--color-surface-2) hover:text-(--color-ink)',
                      )
                    }
                  >
                    {item.icon ? <item.icon className="size-3.5 shrink-0" strokeWidth={2} /> : null}
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  )
}
