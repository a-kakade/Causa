import { ArrowRight } from 'lucide-react'
import { ActionCard } from '@/components/decisions/ActionCard'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingState } from '@/components/common/LoadingState'
import { useDecisions } from '@/hooks/useDecisions'
import type { DecisionResult } from '@/types/decision'
import { formatMonthLabel, titleCase } from '@/lib/format'

const CHAIN_STAGES = ['Driver', 'Controllable lever', 'Action', 'Expected impact', 'Owner', 'Confidence', 'Monitoring', 'Abort condition']

export function DecisionsPage() {
  const { data, isLoading } = useDecisions()

  return (
    <div className="mx-auto max-w-[1200px] space-y-5 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">Decisions</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Recommendations</h1>
      </div>

      <div className="flex flex-wrap items-center gap-1 rounded-(--radius-md) border border-(--color-border) bg-(--color-surface) px-3 py-2 text-[11px] font-medium text-(--color-ink-faint)">
        {CHAIN_STAGES.map((s, i) => (
          <span key={s} className="flex items-center gap-1">
            <span className="rounded-(--radius-xs) bg-(--color-surface-2) px-2 py-1 text-(--color-ink-muted)">{s}</span>
            {i < CHAIN_STAGES.length - 1 ? <ArrowRight className="size-3" /> : null}
          </span>
        ))}
      </div>

      {isLoading || !data ? (
        <LoadingState label="Loading decision engine output" />
      ) : (
        Object.entries(data).map(([key, result]) => <DecisionSection key={key} decisionKey={key} result={result} />)
      )}
    </div>
  )
}

function DecisionSection({ decisionKey, result }: { decisionKey: string; result: DecisionResult }) {
  const ds = result.driverSignal
  return (
    <Card>
      <CardHeader
        title={`${titleCase(ds.driver)} → ${titleCase(ds.kpiId)}`}
        subtitle={`${formatMonthLabel(ds.period)} · ${result.allCandidatesEvaluated} candidates evaluated · request ${result.requestId}`}
      />
      <CardBody className="space-y-3">
        {result.topRecommendation ? (
          <ActionCard action={result.topRecommendation} />
        ) : (
          <EmptyState title="No recommendation cleared for TOP tier" />
        )}

        {result.alternatives.length ? (
          <details>
            <summary className="cursor-pointer text-[12px] font-medium text-(--color-ink-muted)">{result.alternatives.length} alternative(s)</summary>
            <div className="mt-2 space-y-2">
              {result.alternatives.map((a) => (
                <ActionCard key={a.recommendationId} action={a} />
              ))}
            </div>
          </details>
        ) : null}

        {result.conditional.length ? (
          <details>
            <summary className="cursor-pointer text-[12px] font-medium text-(--color-ink-muted)">{result.conditional.length} conditional (needs business context)</summary>
            <div className="mt-2 space-y-2">
              {result.conditional.map((a) => (
                <ActionCard key={a.recommendationId} action={a} />
              ))}
            </div>
          </details>
        ) : null}

        {result.blocked.length ? (
          <details open>
            <summary className="cursor-pointer text-[12px] font-medium text-(--color-negative)">{result.blocked.length} blocked</summary>
            <div className="mt-2 space-y-2">
              {result.blocked.map((a) => (
                <ActionCard key={a.recommendationId} action={a} />
              ))}
            </div>
          </details>
        ) : null}

        <div className="border-t border-(--color-border) pt-2 font-mono text-[10px] text-(--color-ink-faint)">key: {decisionKey}</div>
      </CardBody>
    </Card>
  )
}
