import { CheckCircle2, HelpCircle } from 'lucide-react'

const TERMINAL_PREFIXES = ['ABSTAINED', 'NEEDS_CLARIFICATION', 'BUDGET_EXCEEDED', 'SECURITY_BLOCKED', 'COMPLETED']

export function InvestigationTimeline({ statusHistory }: { statusHistory: string[] }) {
  return (
    <ol className="space-y-0">
      {statusHistory.map((raw, i) => {
        const isTerminal = TERMINAL_PREFIXES.some((p) => raw.startsWith(p))
        const [status, ...rest] = raw.split(' (')
        const detail = rest.length ? rest.join(' (').replace(/\)$/, '') : null
        const isAbstain = raw.startsWith('ABSTAINED')
        const isLast = i === statusHistory.length - 1

        return (
          <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
            {!isLast ? <span className="absolute left-[9px] top-5 h-full w-px bg-(--color-border)" /> : null}
            {isTerminal ? (
              isAbstain ? (
                <HelpCircle className="z-10 size-[18px] shrink-0 text-(--color-confidence-abstain)" strokeWidth={2} />
              ) : (
                <CheckCircle2 className="z-10 size-[18px] shrink-0 text-(--color-positive)" strokeWidth={2} />
              )
            ) : (
              <CheckCircle2 className="z-10 size-[18px] shrink-0 text-(--color-positive)" strokeWidth={2} />
            )}
            <div>
              <p className={`text-[13px] font-semibold ${isAbstain ? 'text-(--color-confidence-abstain)' : 'text-(--color-ink)'}`}>
                {status.replaceAll('_', ' ')}
              </p>
              {detail ? <p className="text-[11px] text-(--color-ink-muted)">{detail}</p> : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
