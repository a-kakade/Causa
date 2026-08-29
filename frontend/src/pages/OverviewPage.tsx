import { AlertTriangle, ArrowRight, CheckCircle2, HelpCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/common/Badge'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { LoadingState } from '@/components/common/LoadingState'
import { SectionHeading } from '@/components/common/SectionHeading'
import { KPIStrip } from '@/components/kpi/KPIStrip'
import { kpiDef } from '@/api'
import { useKpiMovements } from '@/hooks/useKpis'
import { useCurrentStory } from '@/hooks/useNarrative'
import { useCurrentInvestigation } from '@/hooks/useInvestigation'
import { formatPercent } from '@/lib/format'

export function OverviewPage() {
  return (
    <div className="mx-auto max-w-[1400px] space-y-6 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">What requires my attention?</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Overview</h1>
      </div>

      <section>
        <SectionHeading eyebrow="Today at a glance" title="Governed KPIs — click any card to open its investigation" className="mb-3" />
        <KPIStrip />
      </section>

      <div className="grid grid-cols-[1.1fr_1fr] gap-4">
        <AttentionPanel />
        <ExecutiveSummaryCard />
      </div>
    </div>
  )
}

function AttentionPanel() {
  const { data: movements, isLoading } = useKpiMovements()
  const { data: investigation } = useCurrentInvestigation()

  return (
    <Card>
      <CardHeader title="Needs investigation" subtitle="Ranked by materiality — never inferred, only shown when the backend computed a verdict" />
      <CardBody className="space-y-2 !py-2">
        {isLoading || !movements ? (
          <LoadingState label="Loading materiality" />
        ) : (
          movements
            .slice()
            .sort((a, b) => Math.abs(b.percentageChange) - Math.abs(a.percentageChange))
            .map((m) => {
              const def = kpiDef(m.kpiId)
              const isRevenue = m.kpiId === 'revenue'
              const status = isRevenue ? investigation?.status : undefined
              return (
                <Link
                  key={m.kpiId}
                  to={`/investigate/${m.kpiId}`}
                  className="flex items-center justify-between gap-3 rounded-(--radius-md) px-2.5 py-2.5 transition-colors hover:bg-(--color-surface-2)"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-32 shrink-0 text-[13px] font-medium text-(--color-ink)">{def?.name ?? m.kpiId}</div>
                    <span className={`text-[13px] font-semibold tabular ${m.percentageChange >= 0 ? 'text-(--color-positive)' : 'text-(--color-negative)'}`}>
                      {formatPercent(m.percentageChange, { signed: true })}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.materiality ? (
                      <Badge tone={m.materiality === 'CRITICAL' ? 'negative' : 'warning'}>{m.materiality} MATERIALITY</Badge>
                    ) : (
                      <Badge tone="neutral">not assessed</Badge>
                    )}
                    {status ? <InvestigationStatusChip status={status} /> : <Badge tone="neutral">not yet investigated</Badge>}
                    <ArrowRight className="size-3.5 text-(--color-ink-faint)" />
                  </div>
                </Link>
              )
            })
        )}
      </CardBody>
    </Card>
  )
}

function InvestigationStatusChip({ status }: { status: string }) {
  if (status === 'ABSTAINED') {
    return (
      <Badge tone="abstain" icon={<HelpCircle className="size-3" />}>
        Abstained
      </Badge>
    )
  }
  if (status === 'COMPLETED') {
    return (
      <Badge tone="positive" icon={<CheckCircle2 className="size-3" />}>
        Complete
      </Badge>
    )
  }
  return (
    <Badge tone="warning" icon={<AlertTriangle className="size-3" />}>
      {status.replaceAll('_', ' ')}
    </Badge>
  )
}

function ExecutiveSummaryCard() {
  const { data: story, isLoading } = useCurrentStory()

  return (
    <Card>
      <CardHeader title="Executive summary" subtitle="Generated narrative (Step 8) — every statement traces to an evidence ID" />
      <CardBody>
        {isLoading || !story ? (
          <LoadingState label="Loading narrative" />
        ) : (
          <div className="space-y-3">
            <p className="text-[13px] font-semibold leading-snug text-(--color-ink)">{story.headline}</p>
            {story.sections.map((s) => (
              <div key={s.title}>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">{s.title}</p>
                <ul className="mt-1 space-y-1">
                  {s.statements.map((st, i) => (
                    <li key={i} className="text-[13px] leading-snug text-(--color-ink-muted)">
                      {st.text}
                      <span className="ml-1.5 font-mono text-[10px] text-(--color-ink-faint)">
                        [{st.evidenceIds.join(', ')}]
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <Link to="/investigate/revenue" className="inline-flex items-center gap-1 text-[12px] font-medium text-(--color-accent)">
              Open full investigation <ArrowRight className="size-3" />
            </Link>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
