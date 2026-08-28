import { AlertTriangle, CheckCircle2, CircleDashed, XCircle } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import type { ContradictionRecord, Hypothesis, HypothesisResult } from '@/types/investigation'

const STATUS_META: Record<
  HypothesisResult['status'],
  { icon: typeof CheckCircle2; tone: 'positive' | 'warning' | 'negative' | 'neutral'; label: string; iconClass: string }
> = {
  SUPPORTED: { icon: CheckCircle2, tone: 'positive', label: 'Supported', iconClass: 'text-(--color-positive)' },
  PARTIALLY_SUPPORTED: { icon: AlertTriangle, tone: 'warning', label: 'Partially supported', iconClass: 'text-(--color-warning)' },
  CONTRADICTED: { icon: XCircle, tone: 'negative', label: 'Contradicted', iconClass: 'text-(--color-negative)' },
  UNRESOLVED: { icon: CircleDashed, tone: 'neutral', label: 'Unresolved', iconClass: 'text-(--color-ink-faint)' },
  REJECTED: { icon: XCircle, tone: 'negative', label: 'Rejected', iconClass: 'text-(--color-negative)' },
  INCONCLUSIVE: { icon: CircleDashed, tone: 'neutral', label: 'Inconclusive', iconClass: 'text-(--color-ink-faint)' },
}

export function HypothesisCard({
  hypothesis,
  result,
  contradiction,
}: {
  hypothesis: Hypothesis
  result?: HypothesisResult
  contradiction?: ContradictionRecord
}) {
  const meta = result ? STATUS_META[result.status] : STATUS_META.UNRESOLVED
  const Icon = meta.icon

  return (
    <div className="rounded-(--radius-md) border border-(--color-border) p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Icon className={`mt-0.5 size-4 shrink-0 ${meta.iconClass}`} strokeWidth={2} />
          <div>
            <p className="text-[11px] font-mono font-semibold text-(--color-ink-faint)">{hypothesis.hypothesisId}</p>
            <p className="text-[13px] font-medium leading-snug text-(--color-ink)">{hypothesis.statement}</p>
          </div>
        </div>
        {result ? <ConfidenceBadge level={result.confidence} size="sm" /> : null}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pl-6">
        <Badge tone={meta.tone === 'neutral' ? 'neutral' : meta.tone}>{meta.label}</Badge>
        {result ? <Badge tone="neutral">{result.method.replaceAll('_', ' ')}</Badge> : null}
        <Badge tone="neutral">
          {result?.evidenceIds.length ?? 0} evidence
        </Badge>
        {contradiction ? (
          <Badge tone={contradiction.contradictingEvidence.length ? 'warning' : 'neutral'}>
            {contradiction.contradictingEvidence.length} counter-evidence
          </Badge>
        ) : null}
      </div>

      {result?.reasons.length ? (
        <ul className="mt-2 space-y-0.5 pl-6">
          {result.reasons.map((r, i) => (
            <li key={i} className="text-[11px] text-(--color-ink-faint)">
              · {r}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
