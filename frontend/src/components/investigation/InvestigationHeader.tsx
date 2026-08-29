import { ArrowDown, ArrowUp, Check, Download, MessageCircleQuestion, Share2 } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/common/Badge'
import { useAppState } from '@/state/AppStateContext'
import { formatKpiChange, formatKpiValue, formatMonthLabel } from '@/lib/format'
import type { InvestigationState } from '@/types/investigation'
import type { KPIMovement } from '@/types/kpi'
import type { KPIDef } from '@/types/kpi'

export function InvestigationHeader({
  def,
  movement,
  investigationStatus,
  investigation,
  onInvestigate,
}: {
  def: KPIDef
  movement: KPIMovement
  investigationStatus?: string
  /** Full investigation state, when one has run for this KPI/period --
   * Export has nothing to download and Ask follow-up has nothing concrete
   * to reference without it, so both stay enabled either way but Export
   * falls back to just the KPI movement when this is undefined. */
  investigation?: InvestigationState
  onInvestigate: () => void
}) {
  const DirIcon = movement.direction === 'up' ? ArrowUp : ArrowDown
  const { openAskQuestion } = useAppState()
  const [copied, setCopied] = useState(false)

  function handleExport() {
    const payload = investigation ?? { kpiId: def.kpiId, movement }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${def.kpiId}_${movement.period}_investigation.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function handleShare() {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard access can be denied (permissions, insecure context) --
      // fail silently rather than show a copied confirmation that didn't happen.
    }
  }

  return (
    <div className="border-b border-(--color-border) bg-(--color-surface) px-6 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-(--color-ink)">{def.name}</h1>
            <span className="text-sm text-(--color-ink-faint)">{formatMonthLabel(movement.period)}</span>
            {movement.materiality ? (
              <Badge tone={movement.materiality === 'CRITICAL' ? 'negative' : 'warning'}>{movement.materiality.replaceAll('_', ' ')} MATERIALITY</Badge>
            ) : null}
            {investigationStatus ? (
              <Badge tone={investigationStatus === 'ABSTAINED' ? 'abstain' : 'positive'}>
                Investigation {investigationStatus === 'ABSTAINED' ? 'abstained' : investigationStatus.toLowerCase().replaceAll('_', ' ')}
              </Badge>
            ) : null}
          </div>
          <div className="mt-1.5 flex items-baseline gap-3">
            <span className="text-2xl font-bold tabular text-(--color-ink)">
              {formatKpiValue(movement.currentValue, def.unit)}
            </span>
            <span className={`flex items-center gap-0.5 text-sm font-bold tabular ${movement.favorable ? 'text-(--color-positive)' : 'text-(--color-negative)'}`}>
              <DirIcon className="size-3.5" strokeWidth={2.5} />
              {Math.abs(movement.percentageChange).toFixed(1)}%
            </span>
          </div>
          <p className="mt-1 text-[12px] text-(--color-ink-muted)">
            Previous: <span className="tabular font-medium">{formatKpiValue(movement.previousValue, def.unit)}</span>
            <span className="mx-1.5 text-(--color-ink-faint)">·</span>
            Change: <span className="tabular font-medium">{formatKpiChange(movement.absoluteChange, def.unit)}</span>
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
            onClick={() => openAskQuestion(`Why did ${def.name} move the way it did? `)}
            className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-2 text-[13px] font-medium text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <MessageCircleQuestion className="size-3.5" /> Ask follow-up
          </button>
          <button
            type="button"
            onClick={handleExport}
            className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-2 text-[13px] font-medium text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <Download className="size-3.5" /> Export
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-2 text-[13px] font-medium text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            {copied ? <Check className="size-3.5" /> : <Share2 className="size-3.5" />}
            {copied ? 'Copied' : 'Share'}
          </button>
        </div>
      </div>
    </div>
  )
}
