import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { ConfidenceFactors } from './ConfidenceFactors'
import type { HypothesisResult } from '@/types/investigation'
import type { ConfidenceLevel } from '@/types/common'

export function ConfidencePanel({ overall, results }: { overall: ConfidenceLevel | null; results: HypothesisResult[] }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Overall confidence</p>
        <ConfidenceBadge level={overall} size="lg" />
      </div>
      <div className="space-y-2.5">
        {results.map((r) => (
          <div key={r.hypothesisId} className="rounded-(--radius-sm) border border-(--color-border) p-2.5">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[11px] font-semibold text-(--color-ink-faint)">{r.hypothesisId}</p>
              <ConfidenceBadge level={r.confidence} size="sm" />
            </div>
            <div className="mt-1.5">
              <ConfidenceFactors reasons={r.reasons} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
