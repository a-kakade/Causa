import { HelpCircle, Loader2 } from 'lucide-react'
import { HypothesisCard } from '@/components/investigation/HypothesisCard'
import { useAppState } from '@/state/AppStateContext'
import type { ConfidenceLevel } from '@/types/common'
import type { ContradictionRecord, Hypothesis, HypothesisResult } from '@/types/investigation'

/** Worst-to-best is fine here -- we only need a stable sort, and ABSTAIN/
 * NEEDS_CLARIFICATION/UNKNOWN are all "no real signal" so they tie at the
 * bottom rather than needing their own ranking. */
const CONFIDENCE_RANK: Record<ConfidenceLevel, number> = {
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
  ABSTAIN: 0,
  NEEDS_CLARIFICATION: 0,
  UNKNOWN: 0,
}

/**
 * Abstention is a successful system state, not a failure to render around --
 * spec §34: "Never show fabricated explanations." That constraint stays:
 * this never invents a confidence number or a conclusion the backend didn't
 * reach. What it does do is stop hiding the ranked hypotheses behind a blank
 * "insufficient evidence" card -- the backend already scored every
 * hypothesis it generated, so surface that ranking (real, often LOW,
 * confidence scores and all) as "leading candidates" instead.
 */
export function AbstentionState({
  hypotheses, results, contradictions, reasons, kpiName, onInvestigateFurther, investigateFurtherPending,
}: {
  hypotheses: Hypothesis[]
  results?: HypothesisResult[]
  contradictions?: ContradictionRecord[]
  reasons: string[]
  /** Human-readable KPI name, used only to seed the "ask a clarifying
   * question" prefill text -- purely cosmetic, never sent anywhere on its
   * own without the user editing/submitting the modal themselves. */
  kpiName?: string
  /** Re-runs the same investigation (a fresh, real run -- not a retry of the
   * same cached result) so the abstained hypotheses get a new evidence pass. */
  onInvestigateFurther?: () => void
  investigateFurtherPending?: boolean
}) {
  const { openAskQuestion } = useAppState()
  const resultsById = new Map((results ?? []).map((r) => [r.hypothesisId, r]))
  const contradictionsById = new Map((contradictions ?? []).map((c) => [c.hypothesisId, c]))
  const ranked = [...hypotheses].sort((a, b) => {
    const ra = resultsById.get(a.hypothesisId)?.confidence
    const rb = resultsById.get(b.hypothesisId)?.confidence
    return (CONFIDENCE_RANK[rb ?? 'UNKNOWN'] ?? 0) - (CONFIDENCE_RANK[ra ?? 'UNKNOWN'] ?? 0)
  })
  // A hypothesis can individually reach SUPPORTED while the investigation as
  // a whole still abstains -- overall confidence is gated on every
  // hypothesis clearing the bar, not just the best one. Track this
  // separately so the banner never claims "none reached SUPPORTED" while a
  // SUPPORTED badge sits right below it.
  const supportedCount = ranked.filter((h) => resultsById.get(h.hypothesisId)?.status === 'SUPPORTED').length

  return (
    <div className="rounded-(--radius-lg) border-2 border-dashed border-(--color-confidence-abstain) bg-(--color-confidence-abstain-soft) p-6">
      <div className="flex items-center gap-2.5">
        <HelpCircle className="size-6 text-(--color-confidence-abstain)" strokeWidth={2} />
        <p className="text-lg font-bold uppercase tracking-wide text-(--color-confidence-abstain)">
          {supportedCount > 0
            ? `Leading candidate${supportedCount > 1 ? 's' : ''} — investigation still abstained overall`
            : ranked.length
              ? 'Leading candidates — none reached SUPPORTED'
              : 'Insufficient evidence'}
        </p>
      </div>
      <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-(--color-ink)">
        {supportedCount > 0 ? (
          <>
            {supportedCount} of {ranked.length} hypotheses reached SUPPORTED on its own evidence — ranked first below
            — but the investigation abstains overall because at least one other hypothesis didn't clear the bar.
            Nothing here is a fabricated summary: every status and score is exactly what the backend computed.
          </>
        ) : ranked.length ? (
          <>
            The system could not reach SUPPORTED status on any hypothesis with the evidence retrieved for this
            investigation. Ranked below by their actual confidence score — none is presented as a conclusion, and the
            scores are exactly what the backend computed, not a fabricated best guess.
          </>
        ) : (
          <>
            The system could not reach SUPPORTED status on any hypothesis with the evidence retrieved for this
            investigation. Rather than present a low-confidence guess as a conclusion, it abstained — this is the
            governed, expected behavior when evidence doesn't clear the bar.
          </>
        )}
      </p>

      {ranked.length ? (
        <div className="mt-4 space-y-2.5">
          {ranked.map((h) => (
            <HypothesisCard
              key={h.hypothesisId}
              hypothesis={h}
              result={resultsById.get(h.hypothesisId)}
              contradiction={contradictionsById.get(h.hypothesisId)}
            />
          ))}
        </div>
      ) : null}

      {reasons.length ? (
        <div className="mt-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Evidence that would change this</p>
          <ul className="mt-1 space-y-1">
            {reasons.map((r, i) => (
              <li key={i} className="text-[13px] text-(--color-ink-muted)">
                • {r}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 flex gap-2">
        <button
          type="button"
          onClick={onInvestigateFurther}
          disabled={!onInvestigateFurther || investigateFurtherPending}
          className="flex items-center gap-1.5 rounded-(--radius-sm) bg-(--color-accent) px-3.5 py-2 text-[13px] font-semibold text-(--color-ink-inverse) transition-colors hover:bg-(--color-accent-strong) disabled:opacity-50"
        >
          {investigateFurtherPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {investigateFurtherPending ? 'Re-investigating…' : 'Investigate further'}
        </button>
        <button
          type="button"
          onClick={() =>
            openAskQuestion(kpiName ? `Why did ${kpiName} move the way it did? ` : '')
          }
          className="rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3.5 py-2 text-[13px] font-semibold text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
        >
          Ask a clarifying question
        </button>
      </div>
    </div>
  )
}
