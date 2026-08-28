import { CheckCircle2, CircleDashed, XCircle } from 'lucide-react'
import type { EligibilityCheck, EligibilityReport } from '@/types/causal'

const STATUS_ICON: Record<EligibilityCheck['status'], { icon: typeof CheckCircle2; className: string }> = {
  PASS: { icon: CheckCircle2, className: 'text-(--color-positive)' },
  HARD_FAIL: { icon: XCircle, className: 'text-(--color-negative)' },
  SOFT_FAIL: { icon: XCircle, className: 'text-(--color-warning)' },
  NOT_APPLICABLE: { icon: CircleDashed, className: 'text-(--color-ink-faint)' },
}

export function EligibilityChecklist({ report }: { report: EligibilityReport }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">
        Eligibility · {report.checks.length} checks, fixed order — verdict {report.verdict.replaceAll('_', ' ')}
      </p>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1">
        {report.checks.map((c) => {
          const meta = STATUS_ICON[c.status]
          const Icon = meta.icon
          return (
            <li key={c.checkName} className="flex items-start gap-1.5 text-[12px]">
              <Icon className={`mt-0.5 size-3.5 shrink-0 ${meta.className}`} strokeWidth={2} />
              <div>
                <span className="font-medium text-(--color-ink)">{c.checkName.replaceAll('_', ' ')}</span>
                <p className="text-[11px] text-(--color-ink-faint)">{c.reason}</p>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
