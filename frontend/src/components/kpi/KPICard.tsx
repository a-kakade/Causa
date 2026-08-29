import { ArrowDown, ArrowRight, ArrowUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/common/Badge'
import { directionTone } from '@/lib/colors'
import { formatKpiValue, formatMonthLabel, formatPercent } from '@/lib/format'
import type { KPIDef } from '@/types/kpi'
import type { KPIMovement } from '@/types/kpi'

export function KPICard({ def, movement }: { def: KPIDef; movement: KPIMovement }) {
  const DirectionIcon = movement.direction === 'up' ? ArrowUp : movement.direction === 'down' ? ArrowDown : ArrowRight
  const tone = directionTone(movement.direction, movement.favorable)

  return (
    <Link
      to={`/investigate/${def.kpiId}`}
      className="group flex flex-col justify-between rounded-(--radius-lg) border border-(--color-border) bg-(--color-surface) p-4 transition-colors hover:border-(--color-accent-border)"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-[12px] font-medium text-(--color-ink-muted)">{def.name}</p>
        {movement.materiality ? (
          <Badge tone={movement.materiality === 'CRITICAL' ? 'negative' : 'warning'}>{movement.materiality.replaceAll('_', ' ')}</Badge>
        ) : null}
      </div>

      <p className="mt-2 text-2xl font-semibold tabular text-(--color-ink)">{formatKpiValue(movement.currentValue, def.unit)}</p>

      <div className="mt-2 flex items-center gap-1.5 text-[12px] font-semibold tabular">
        <span className={`flex items-center gap-0.5 ${tone}`}>
          <DirectionIcon className="size-3" strokeWidth={2.5} />
          {formatPercent(Math.abs(movement.percentageChange))}
        </span>
        <span className="text-(--color-ink-faint)">vs {formatMonthLabel(movement.previousPeriod)}</span>
      </div>
    </Link>
  )
}
