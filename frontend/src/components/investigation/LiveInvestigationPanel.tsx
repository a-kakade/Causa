import { CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Hypothesis } from '@/types/investigation'

const STAGES = [
  'KPI movement confirmed',
  'Materiality established',
  'Generating hypotheses',
  'Gathering evidence',
  'Testing counter-evidence',
  'Evaluating causal validity',
  'Calibrating confidence',
  'Preparing recommendation',
]

/**
 * Presentation-layer replay only. No tool call happens here — the backend
 * already ran this investigation once, offline (see step5_validation.json).
 * This component paces through the REAL resulting hypotheses/stages so a
 * viewer can watch the shape of the process; it never invents a step the
 * backend didn't actually execute.
 */
export function LiveInvestigationPanel({ hypotheses, onDone }: { hypotheses: Hypothesis[]; onDone: () => void }) {
  const [stageIndex, setStageIndex] = useState(0)

  useEffect(() => {
    if (stageIndex >= STAGES.length) {
      const t = setTimeout(onDone, 500)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setStageIndex((i) => i + 1), 420)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageIndex])

  return (
    <div className="rounded-(--radius-lg) border border-(--color-accent-border) bg-(--color-accent-soft) p-5">
      <p className="text-[12px] font-bold uppercase tracking-wide text-(--color-accent-strong)">Investigating Revenue</p>
      <ul className="mt-3 space-y-1.5">
        {STAGES.map((stage, i) => {
          const done = i < stageIndex
          const active = i === stageIndex
          return (
            <li key={stage} className="flex items-center gap-2 text-[13px]">
              {done ? (
                <CheckCircle2 className="size-4 text-(--color-positive)" />
              ) : active ? (
                <Loader2 className="size-4 animate-spin text-(--color-accent)" />
              ) : (
                <span className="size-4 rounded-full border border-(--color-border-strong)" />
              )}
              <span className={done ? 'text-(--color-ink)' : active ? 'font-medium text-(--color-ink)' : 'text-(--color-ink-faint)'}>{stage}</span>
            </li>
          )
        })}
      </ul>
      {stageIndex >= 2 ? (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-(--color-accent-border) pt-3">
          {hypotheses.map((h) => (
            <span key={h.hypothesisId} className="rounded-(--radius-xs) bg-(--color-surface) px-2 py-1 font-mono text-[11px] text-(--color-ink-muted)">
              {h.hypothesisId} {h.driver}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
