import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { LoadingState } from '@/components/common/LoadingState'
import { formatDuration, formatMonthLabel } from '@/lib/format'
import { useInvestigationByRole } from '@/hooks/useInvestigation'

export function InvestigateHistoryPage() {
  const { data: analyst, isLoading: la } = useInvestigationByRole('ANALYST')
  const { data: executive, isLoading: le } = useInvestigationByRole('EXECUTIVE')

  return (
    <div className="mx-auto max-w-[1000px] space-y-4 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">Investigations</p>
        <h1 className="text-xl font-bold text-(--color-ink)">History</h1>
      </div>

      {la || le ? <LoadingState label="Loading investigation history" /> : null}

      {[
        { role: 'Analyst', inv: analyst },
        { role: 'Executive', inv: executive },
      ].map(({ role, inv }) =>
        inv ? (
          <Link key={role} to={`/investigate/${inv.kpiId}`}>
            <Card className="transition-colors hover:border-(--color-accent-border)">
              <CardHeader
                title={`Revenue — ${formatMonthLabel(inv.period)} (${role} run)`}
                subtitle={`${inv.investigationId} · ${inv.budgets.usedAgentCalls} agent calls · ${inv.budgets.usedToolCalls} tool calls`}
                action={<ConfidenceBadge level={inv.confidence} />}
              />
              <CardBody className="flex items-center justify-between">
                <p className="text-[12px] text-(--color-ink-muted)">
                  Status: <span className="font-semibold text-(--color-ink)">{inv.status}</span>
                  <span className="mx-1.5">·</span>
                  {inv.statusHistory.length} stages
                  <span className="mx-1.5">·</span>
                  {formatDuration(inv.telemetry.reduce((n, t) => n + t.totalLatencyMs, 0))} total agent latency
                </p>
                <ArrowRight className="size-4 text-(--color-ink-faint)" />
              </CardBody>
            </Card>
          </Link>
        ) : null,
      )}
    </div>
  )
}
