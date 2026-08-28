import { titleCase } from '@/lib/format'
import type { ContradictionCheck } from '@/types/evidence'
import type { ContradictionRecord } from '@/types/investigation'

export function ContradictionPanel({ contradictions, checks }: { contradictions: ContradictionRecord[]; checks: ContradictionCheck[] }) {
  const totalSupporting = contradictions.reduce((n, c) => n + c.supportingEvidence.length, 0)
  const totalContradicting = contradictions.reduce((n, c) => n + c.contradictingEvidence.length, 0)
  const flaggedChecks = checks.filter((c) => c.contradicts)

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-(--radius-md) border border-(--color-positive-soft) bg-(--color-positive-soft) p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-positive)">Evidence for</p>
          <p className="text-2xl font-bold tabular text-(--color-positive)">{totalSupporting}</p>
          <p className="text-[11px] text-(--color-ink-muted)">evidence items</p>
        </div>
        <div className="rounded-(--radius-md) border border-(--color-negative-soft) bg-(--color-negative-soft) p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-negative)">Evidence against</p>
          <p className="text-2xl font-bold tabular text-(--color-negative)">{totalContradicting}</p>
          <p className="text-[11px] text-(--color-ink-muted)">evidence items</p>
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">
          Category-level contradiction checks (two-proportion z-test, low-score rate Oct → Nov)
        </p>
        <div className="scrollbar-thin max-h-56 space-y-1 overflow-y-auto">
          {checks.map((c) => (
            <div
              key={c.segment}
              className={`flex items-center justify-between rounded-(--radius-sm) px-2.5 py-1.5 text-[12px] ${
                c.contradicts ? 'bg-(--color-warning-soft)' : 'bg-(--color-surface-2)'
              }`}
            >
              <span className="font-medium text-(--color-ink)">{titleCase(c.segment)}</span>
              <span className="tabular text-(--color-ink-muted)">
                {(c.previousLowScoreRate * 100).toFixed(1)}% → {(c.currentLowScoreRate * 100).toFixed(1)}% low-score
                <span className="ml-2 font-mono text-(--color-ink-faint)">z={c.zScore.toFixed(2)}</span>
              </span>
            </div>
          ))}
        </div>
        <p className="mt-1.5 text-[11px] text-(--color-ink-faint)">
          {flaggedChecks.length
            ? `${flaggedChecks.length} segment(s) flagged as statistically contradicting.`
            : 'No segment reached statistical significance as a contradiction in this run.'}
        </p>
      </div>
    </div>
  )
}
