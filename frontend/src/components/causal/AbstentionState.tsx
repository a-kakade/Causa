import { HelpCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Hypothesis } from '@/types/investigation'

/**
 * Abstention is a successful system state, not a failure to render around.
 * This screen is deliberately as prominent as a completed conclusion would
 * be — spec §34: "Never show fabricated explanations."
 */
export function AbstentionState({ hypotheses, reasons }: { hypotheses: Hypothesis[]; reasons: string[] }) {
  return (
    <div className="rounded-(--radius-lg) border-2 border-dashed border-(--color-confidence-abstain) bg-(--color-confidence-abstain-soft) p-6">
      <div className="flex items-center gap-2.5">
        <HelpCircle className="size-6 text-(--color-confidence-abstain)" strokeWidth={2} />
        <p className="text-lg font-bold uppercase tracking-wide text-(--color-confidence-abstain)">Insufficient evidence</p>
      </div>
      <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-(--color-ink)">
        The system could not reach SUPPORTED status on any hypothesis with the evidence retrieved for this investigation. Rather
        than present a low-confidence guess as a conclusion, it abstained — this is the governed, expected behavior when
        evidence doesn't clear the bar.
      </p>

      {hypotheses.length ? (
        <div className="mt-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">The system cannot distinguish between</p>
          <ul className="mt-1 space-y-1">
            {hypotheses.map((h) => (
              <li key={h.hypothesisId} className="text-[13px] text-(--color-ink-muted)">
                • {h.statement}
              </li>
            ))}
          </ul>
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
          className="rounded-(--radius-sm) bg-(--color-accent) px-3.5 py-2 text-[13px] font-semibold text-(--color-ink-inverse) transition-colors hover:bg-(--color-accent-strong)"
        >
          Investigate further
        </button>
        <Link
          to="/evidence"
          className="rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3.5 py-2 text-[13px] font-semibold text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
        >
          Ask a clarifying question
        </Link>
      </div>
    </div>
  )
}
