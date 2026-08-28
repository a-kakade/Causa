import { ArrowDown, ArrowUp } from 'lucide-react'
import { kpiDef } from '@/api/demoAdapter/kpiRegistry'
import { formatPercent } from '@/lib/format'
import type { KPIMovement } from '@/types/kpi'

/** Spec §19: neutral wording only ("moved alongside" / "concurrent movement")
 * — never implies causality between these KPIs and the investigated one. */
export function ConcurrentKpiPanel({ movements }: { movements: KPIMovement[] }) {
  return (
    <div>
      <p className="mb-2 text-[11px] text-(--color-ink-faint)">Moved alongside, in the same period — concurrent context only, not a claimed relationship.</p>
      <div className="grid grid-cols-2 gap-2">
        {movements.map((m) => {
          const def = kpiDef(m.kpiId)
          const Icon = m.direction === 'up' ? ArrowUp : ArrowDown
          return (
            <div key={m.kpiId} className="flex items-center justify-between rounded-(--radius-sm) border border-(--color-border) px-2.5 py-2">
              <span className="text-[12px] font-medium text-(--color-ink)">{def?.name ?? m.kpiId}</span>
              <span className={`flex items-center gap-0.5 text-[12px] font-semibold tabular ${m.favorable ? 'text-(--color-positive)' : 'text-(--color-negative)'}`}>
                <Icon className="size-3" strokeWidth={2.5} />
                {formatPercent(Math.abs(m.percentageChange))}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
