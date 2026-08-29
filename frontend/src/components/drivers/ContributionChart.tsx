import { Lock } from 'lucide-react'
import { Tooltip } from '@/components/common/Tooltip'
import { formatPercent, formatSignedCurrency } from '@/lib/format'
import { titleCase } from '@/lib/format'
import type { SegmentContribution } from '@/types/driver'

export function ContributionChart({ segments, total }: { segments: SegmentContribution[]; total: number }) {
  const max = Math.max(...segments.map((s) => Math.abs(s.contributionValue || 0)), 1)

  return (
    <div className="space-y-1.5">
      {segments.map((s) => {
        if (s.restricted) {
          return (
            <div key={s.rank} className="flex items-center gap-3 rounded-(--radius-sm) bg-(--color-surface-2) px-2.5 py-2 text-[12px] text-(--color-ink-faint)">
              <Lock className="size-3.5 shrink-0" />
              Restricted by your access policy.
            </div>
          )
        }
        const pct = (Math.abs(s.contributionValue) / max) * 100
        const positive = s.contributionValue >= 0
        const shareOfTotal = total ? (s.contributionValue / total) * 100 : null
        return (
          <Tooltip
            key={s.segment}
            content={
              <div className="space-y-0.5">
                <div className="font-semibold">{titleCase(s.segment)}</div>
                <div>{formatSignedCurrency(s.contributionValue)} contribution</div>
                {shareOfTotal !== null ? <div>{formatPercent(shareOfTotal)} of total movement</div> : null}
              </div>
            }
          >
            <div
              tabIndex={0}
              className="group flex cursor-default items-center gap-3 rounded-(--radius-sm) px-1 py-0.5 outline-none transition-colors hover:bg-(--color-surface-2) focus-visible:bg-(--color-surface-2)"
            >
              <div className="w-32 shrink-0 truncate text-[12px] font-medium text-(--color-ink)" title={s.segment}>
                {titleCase(s.segment)}
              </div>
              <div className="relative h-5 flex-1 rounded-(--radius-xs) bg-(--color-surface-2)">
                <div
                  className={`h-full rounded-(--radius-xs) transition-[filter] duration-150 group-hover:brightness-110 ${
                    positive ? 'bg-(--color-positive)' : 'bg-(--color-negative)'
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="w-24 shrink-0 text-right text-[12px] font-semibold tabular text-(--color-ink)">
                {formatSignedCurrency(s.contributionValue)}
              </div>
              {total ? (
                <div className="w-14 shrink-0 text-right text-[11px] tabular text-(--color-ink-faint)">
                  {formatPercent((s.contributionValue / total) * 100)}
                </div>
              ) : null}
            </div>
          </Tooltip>
        )
      })}
    </div>
  )
}
