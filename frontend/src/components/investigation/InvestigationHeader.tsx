import { ArrowDown, ArrowUp, Download, MessageCircleQuestion, Share2 } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import { formatCurrency, formatMonthLabel, formatSignedCurrency } from '@/lib/format'
import type { KPIMovement } from '@/types/kpi'
import type { KPIDef } from '@/types/kpi'

export function InvestigationHeader({
  def,
  movement,
  investigationStatus,
  onInvestigate,
}: {
  def: KPIDef
  movement: KPIMovement
  investigationStatus?: string
  onInvestigate: () => void
}) {
  const DirIcon = movement.direction === 'up' ? ArrowUp : ArrowDown

  return (
    <div className="border-b border-(--color-border) bg-(--color-surface) px-6 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-(--color-ink)">{def.name}</h1>
            <span className="text-sm text-(--color-ink-faint)">{formatMonthLabel(movement.period)}</span>
            {movement.materiality ? (
              <Badge tone={movement.materiality === 'CRITICAL' ? 'negative' : 'warning'}>{movement.materiality} MATERIALITY</Badge>
            ) : null}
            {investigationStatus ? (
              <Badge tone={investigationStatus === 'ABSTAINED' ? 'abstain' : 'positive'}>
                Investigation {investigationStatus === 'ABSTAINED' ? 'abstained' : investigationStatus.toLowerCase().replaceAll('_', ' ')}
              </Badge>
            ) : null}
          </div>
          <div className="mt-1.5 flex items-baseline gap-3">
            <span className="text-2xl font-bold tabular text-(--color-ink)">
              {def.unit === 'currency_brl' ? formatCurrency(movement.currentValue) : movement.currentValue.toLocaleString()}
            </span>
            <span className={`flex items-center gap-0.5 text-sm font-bold tabular ${movement.favorable ? 'text-(--color-positive)' : 'text-(--color-negative)'}`}>
              <DirIcon className="size-3.5" strokeWidth={2.5} />
              {Math.abs(movement.percentageChange).toFixed(1)}%
            </span>
          </div>
          <p className="mt-1 text-[12px] text-(--color-ink-muted)">
            Previous: <span className="tabular font-medium">{def.unit === 'currency_brl' ? formatCurrency(movement.previousValue) : movement.previousValue.toLocaleString()}</span>
            <span className="mx-1.5 text-(--color-ink-faint)">·</span>
            Change: <span className="tabular font-medium">{formatSignedCurrency(movement.absoluteChange)}</span>
          </p>
        </div>

        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={onInvestigate}
            className="rounded-(--radius-sm) bg-(--color-accent) px-3.5 py-2 text-[13px] font-semibold text-(--color-ink-inverse) transition-colors hover:bg-(--color-accent-strong)"
          >
            Investigate
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-2 text-[13px] font-medium text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <MessageCircleQuestion className="size-3.5" /> Ask follow-up
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-2 text-[13px] font-medium text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <Download className="size-3.5" /> Export
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-2 text-[13px] font-medium text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <Share2 className="size-3.5" /> Share
          </button>
        </div>
      </div>
    </div>
  )
}
