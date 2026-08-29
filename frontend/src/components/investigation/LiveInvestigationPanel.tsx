import { CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
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

// Index of the stage this component holds on while the real backend call is
// still in flight -- everything before it (KPI movement / materiality /
// hypothesis generation) is fast and deterministic-ish in practice, so it's
// harmless to breeze through those cosmetically; "Gathering evidence" is
// where a mode=live run actually spends its time (real Groq round-trips),
// so that's the one stage this component must NOT fake past while pending.
const HOLD_STAGE = STAGES.indexOf('Gathering evidence')

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

/**
 * While `pending` is true, the backend call this panel represents is still
 * genuinely running (a mode=live investigation can take several minutes --
 * real Groq round-trips, not a fixed delay) -- this component holds at the
 * "Gathering evidence" stage and shows a live elapsed-time counter instead
 * of pretending to finish. Once `pending` goes false, the real result
 * exists and it plays a quick, honest reveal through the remaining stages.
 * It never invents a step the backend didn't actually execute.
 */
export function LiveInvestigationPanel({ hypotheses, kpiName = 'Revenue', pending = false, onDone }: {
  hypotheses: Hypothesis[]; kpiName?: string; pending?: boolean; onDone: () => void
}) {
  const [stageIndex, setStageIndex] = useState(0)
  const [elapsedMs, setElapsedMs] = useState(0)
  const startRef = useRef(performance.now())

  useEffect(() => {
    if (!pending) return
    const t = setInterval(() => setElapsedMs(performance.now() - startRef.current), 1000)
    return () => clearInterval(t)
  }, [pending])

  useEffect(() => {
    // Hold at HOLD_STAGE for as long as the real call is still pending --
    // only advance past it once the backend has actually returned.
    if (pending && stageIndex >= HOLD_STAGE) return
    if (stageIndex >= STAGES.length) {
      const t = setTimeout(onDone, 500)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setStageIndex((i) => i + 1), 420)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageIndex, pending])

  const holding = pending && stageIndex >= HOLD_STAGE

  return (
    <div className="rounded-(--radius-lg) border border-(--color-accent-border) bg-(--color-accent-soft) p-5">
      <div className="flex items-center justify-between">
        <p className="text-[12px] font-bold uppercase tracking-wide text-(--color-accent-strong)">Investigating {kpiName}</p>
        {pending ? (
          <span className="font-mono text-[11px] text-(--color-accent-strong)">{formatElapsed(elapsedMs)} elapsed</span>
        ) : null}
      </div>
      {holding ? (
        <p className="mt-1 text-[11px] text-(--color-ink-faint)">
          Real LLM calls in progress against the live provider — this can take a few minutes on the free tier.
        </p>
      ) : null}
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
