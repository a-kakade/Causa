import { useState } from 'react'
import { Check, ChevronDown, ChevronUp, Pencil, X } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import { formatPercent } from '@/lib/format'
import type { ActionRecommendation } from '@/types/decision'

const TIER_TONE: Record<ActionRecommendation['tier'], 'positive' | 'warning' | 'neutral' | 'negative'> = {
  TOP: 'positive',
  ALTERNATIVE: 'neutral',
  CONDITIONAL: 'warning',
  BLOCKED: 'negative',
}

export function ActionCard({ action }: { action: ActionRecommendation }) {
  const [expanded, setExpanded] = useState(false)
  const [decision, setDecision] = useState<'pending' | 'approved' | 'rejected'>('pending')

  return (
    <div className="rounded-(--radius-md) border border-(--color-border) p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5">
            <Badge tone={TIER_TONE[action.tier]}>{action.tier}</Badge>
            {!action.actionJustifiedByEvidence ? <Badge tone="warning">not evidence-backed</Badge> : <Badge tone="positive">evidence-backed</Badge>}
          </div>
          <p className="mt-1.5 text-[14px] font-semibold text-(--color-ink)">{action.possibleAction}</p>
          <p className="text-[12px] text-(--color-ink-muted)">
            Driver: <span className="font-medium">{action.driver.replaceAll('_', ' ')}</span> · Lever:{' '}
            <span className="font-medium">{action.controllableLever.replaceAll('_', ' ')}</span> · Owner:{' '}
            <span className="font-medium">{action.owner}</span>
          </p>
        </div>
        <div className="text-right">
          <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">Priority score</p>
          <p className="text-lg font-bold tabular text-(--color-ink)">{action.priorityScore.toFixed(1)}</p>
        </div>
      </div>

      <div className="mt-2.5 grid grid-cols-3 gap-3 rounded-(--radius-sm) bg-(--color-surface-2) p-2.5">
        <MiniStat label="Expected effect" value={`${action.expectedImpact.estimatedEffect > 0 ? '+' : ''}${action.expectedImpact.estimatedEffect} ${action.expectedImpact.effectUnit}`} />
        <MiniStat label="Confidence" value={formatPercent(action.expectedImpact.confidence * 100)} />
        <MiniStat label="Addressable population" value={action.expectedImpact.addressablePopulation?.toLocaleString() ?? '—'} />
      </div>

      {decision === 'pending' ? (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => setDecision('approved')}
            className="flex items-center gap-1 rounded-(--radius-sm) bg-(--color-positive) px-3 py-1.5 text-[12px] font-semibold text-white transition-colors hover:opacity-90"
          >
            <Check className="size-3.5" /> Approve
          </button>
          <button
            type="button"
            onClick={() => setDecision('rejected')}
            className="flex items-center gap-1 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-1.5 text-[12px] font-semibold text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <X className="size-3.5" /> Reject
          </button>
          <button
            type="button"
            className="flex items-center gap-1 rounded-(--radius-sm) border border-(--color-border-strong) bg-(--color-surface) px-3 py-1.5 text-[12px] font-semibold text-(--color-ink) transition-colors hover:bg-(--color-surface-2)"
          >
            <Pencil className="size-3.5" /> Modify
          </button>
        </div>
      ) : (
        <div className="mt-3">
          <Badge tone={decision === 'approved' ? 'positive' : 'negative'}>
            {decision === 'approved' ? 'Approved — pending owner action' : 'Rejected'}
          </Badge>
        </div>
      )}

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mt-2.5 flex items-center gap-1 text-[11px] font-medium text-(--color-accent)"
      >
        {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        Why this recommendation?
      </button>

      {expanded ? (
        <div className="mt-2.5 space-y-2.5 border-t border-(--color-border) pt-2.5">
          <p className="text-[12px] text-(--color-ink-muted)">{action.rationale}</p>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Assumptions</p>
            <ul className="list-disc space-y-0.5 pl-4">
              {action.assumptions.map((a, i) => (
                <li key={i} className="text-[12px] text-(--color-ink-muted)">
                  {a}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Constraints</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {action.constraints.map((c) => (
                <Badge key={c.constraint} tone={c.status === 'PASS' ? 'positive' : c.status === 'WARNING' ? 'warning' : 'negative'}>
                  {c.constraint.replaceAll('_', ' ')}: {c.status}
                </Badge>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Monitoring plan</p>
            {action.monitoringKpis.map((m) => (
              <p key={m.kpi} className="text-[12px] text-(--color-ink-muted)">
                {m.kpi.replaceAll('_', ' ')} — target: {m.target}. Abort if: {m.stopCondition}.
              </p>
            ))}
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Score breakdown</p>
            <p className="font-mono text-[11px] text-(--color-ink-faint)">{action.scoreBreakdown.priorityFormula}</p>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{label}</p>
      <p className="text-[13px] font-semibold tabular text-(--color-ink)">{value}</p>
    </div>
  )
}
