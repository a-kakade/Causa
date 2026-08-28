import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { kpiDef } from '@/api/demoAdapter/kpiRegistry'
import { AbstentionState } from '@/components/causal/AbstentionState'
import { CausalPanel } from '@/components/causal/CausalPanel'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { LoadingState } from '@/components/common/LoadingState'
import { SectionHeading } from '@/components/common/SectionHeading'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/common/Tabs'
import { ConfidencePanel } from '@/components/confidence/ConfidencePanel'
import { ContributionChart } from '@/components/drivers/ContributionChart'
import { DriverDrilldown } from '@/components/drivers/DriverDrilldown'
import { PVMWaterfall } from '@/components/drivers/PVMWaterfall'
import { AgentTrace } from '@/components/investigation/AgentTrace'
import { ConcurrentKpiPanel } from '@/components/investigation/ConcurrentKpiPanel'
import { ContradictionPanel } from '@/components/investigation/ContradictionPanel'
import { HypothesisCard } from '@/components/investigation/HypothesisCard'
import { InvestigationHeader } from '@/components/investigation/InvestigationHeader'
import { InvestigationTimeline } from '@/components/investigation/InvestigationTimeline'
import { LiveInvestigationPanel } from '@/components/investigation/LiveInvestigationPanel'
import { KPITrend } from '@/components/kpi/KPITrend'
import { useCausalResults } from '@/hooks/useCausal'
import { useConcurrentKpiMovements, useDriverDecomposition } from '@/hooks/useDrivers'
import { useContradictionChecks } from '@/hooks/useEvidence'
import { useCurrentInvestigation } from '@/hooks/useInvestigation'
import { useKpiMovement } from '@/hooks/useKpis'
import { useAllLogs } from '@/hooks/useLogs'
import { formatCurrency } from '@/lib/format'

export function InvestigatePage() {
  const { kpiId = 'revenue' } = useParams()
  const [params] = useSearchParams()
  const initialTab = params.get('tab') ?? 'overview'
  const [tab, setTab] = useState(initialTab)
  const [liveMode, setLiveMode] = useState(false)
  const [revealed, setRevealed] = useState(true)

  const def = kpiDef(kpiId)
  const { data: movement, isLoading: loadingMovement } = useKpiMovement(kpiId)
  const isRevenue = kpiId === 'revenue'

  const { data: decomposition } = useDriverDecomposition()
  const { data: concurrent } = useConcurrentKpiMovements()
  const { data: investigation } = useCurrentInvestigation()
  const { data: causalResults } = useCausalResults()
  const { data: contradictionChecks } = useContradictionChecks()
  const { data: logs } = useAllLogs()

  if (!def) return <ErrorState title="Unknown KPI" message={`No governed KPI contract for "${kpiId}".`} />
  if (loadingMovement || !movement) return <LoadingState label="Loading KPI movement" />

  const scopedLogs = (logs ?? []).filter((l) => l.investigationId === investigation?.investigationId)

  function handleInvestigate() {
    setRevealed(false)
    setLiveMode(true)
  }

  return (
    <div className="mx-auto max-w-[1400px]">
      <InvestigationHeader
        def={def}
        movement={movement}
        investigationStatus={isRevenue ? investigation?.status : undefined}
        onInvestigate={handleInvestigate}
      />

      {liveMode ? (
        <div className="px-6 pt-4">
          <LiveInvestigationPanel
            hypotheses={investigation?.hypotheses ?? []}
            onDone={() => {
              setLiveMode(false)
              setRevealed(true)
            }}
          />
        </div>
      ) : null}

      {revealed ? (
        <Tabs value={tab} onValueChange={setTab} className="px-6 py-4">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="process">Process</TabsTrigger>
            <TabsTrigger value="logs">Logs</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-4 space-y-4">
            <div className="grid grid-cols-[1.4fr_1fr] gap-4">
              <Card>
                <CardHeader title="What changed" subtitle={`${formatCurrency(movement.previousValue)} → ${formatCurrency(movement.currentValue)}`} />
                <CardBody>
                  <KPITrend kpiId={kpiId} valueFormatter={def.unit === 'currency_brl' ? formatCurrency : undefined} />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Confidence" subtitle={isRevenue ? 'From the real Step 5 agent run' : 'No investigation run for this KPI yet'} />
                <CardBody>
                  {isRevenue && investigation ? (
                    <ConfidencePanel overall={investigation.confidence} results={investigation.hypothesisResults} />
                  ) : (
                    <EmptyState title="Not investigated" description="Click Investigate to run this KPI through the pipeline." />
                  )}
                </CardBody>
              </Card>
            </div>

            {isRevenue && decomposition ? (
              <Card>
                <CardHeader title="Why did it move?" subtitle="Price-Volume-Mix decomposition — deterministic, never a causal claim" />
                <CardBody>
                  <PVMWaterfall pvm={decomposition.pvm} previousValue={movement.previousValue} currentValue={movement.currentValue} />
                  <div className="mt-4">
                    <DriverDrilldown decomposition={decomposition} />
                  </div>
                </CardBody>
              </Card>
            ) : null}

            <div className="grid grid-cols-2 gap-4">
              <Card>
                <CardHeader title="Investigation" subtitle="Hypotheses generated and tested" />
                <CardBody className="space-y-2.5">
                  {isRevenue && investigation ? (
                    investigation.status === 'ABSTAINED' && investigation.hypothesisResults.every((r) => r.evidenceIds.length === 0) ? (
                      <AbstentionState
                        hypotheses={investigation.hypotheses}
                        reasons={[
                          'Additional evidence retrieval rounds for this KPI/period',
                          'Segment-level evidence beyond the concurrent-KPI signals already gathered',
                        ]}
                      />
                    ) : (
                      investigation.hypotheses.map((h) => (
                        <HypothesisCard
                          key={h.hypothesisId}
                          hypothesis={h}
                          result={investigation.hypothesisResults.find((r) => r.hypothesisId === h.hypothesisId)}
                          contradiction={investigation.contradictions.find((c) => c.hypothesisId === h.hypothesisId)}
                        />
                      ))
                    )
                  ) : (
                    <EmptyState title="No hypotheses yet" description="This KPI has not been run through the investigation engine in this demo." />
                  )}
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Concurrent KPI movement" />
                <CardBody>{concurrent ? <ConcurrentKpiPanel movements={concurrent} /> : <LoadingState />}</CardBody>
              </Card>
            </div>

            {isRevenue ? (
              <Card>
                <CardHeader title="Counter-evidence & contradictions" />
                <CardBody>
                  {investigation && contradictionChecks ? (
                    <ContradictionPanel contradictions={investigation.contradictions} checks={contradictionChecks} />
                  ) : (
                    <LoadingState />
                  )}
                </CardBody>
              </Card>
            ) : null}

            {isRevenue && causalResults ? (
              <Card>
                <CardHeader title="Causal analysis" subtitle="Evidence-tier engine — T1–T4, deterministic eligibility + method selection" />
                <CardBody className="space-y-3">
                  {causalResults.map((r) => (
                    <CausalPanel key={r.hypothesisId} result={r} />
                  ))}
                </CardBody>
              </Card>
            ) : null}

            <div className="flex justify-end">
              <Link to="/decisions" className="text-[12px] font-medium text-(--color-accent)">
                View recommended actions for this driver →
              </Link>
            </div>
          </TabsContent>

          <TabsContent value="evidence" className="mt-4">
            {decomposition ? (
              <Card>
                <CardHeader title="Top category contributors" />
                <CardBody>
                  <ContributionChart segments={decomposition.topCategoryContributions} total={decomposition.pvm.volumeEffect} />
                </CardBody>
              </Card>
            ) : null}
            <div className="mt-3">
              <Link to="/evidence" className="text-[12px] font-medium text-(--color-accent)">
                Open the full Evidence Explorer →
              </Link>
            </div>
          </TabsContent>

          <TabsContent value="process" className="mt-4 space-y-4">
            <SectionHeading eyebrow="Investigation execution" title="Process trace" />
            <div className="grid grid-cols-[1fr_1.2fr] gap-4">
              <Card>
                <CardHeader title="Stages" />
                <CardBody>
                  {investigation ? <InvestigationTimeline statusHistory={investigation.statusHistory} /> : <LoadingState />}
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Agent trace" subtitle="Structured metadata only — no chain-of-thought exposed" />
                <CardBody>
                  {investigation ? <AgentTrace auditTrace={investigation.auditTrace} telemetry={investigation.telemetry} /> : <LoadingState />}
                </CardBody>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="logs" className="mt-4">
            <Card>
              <CardHeader title="Audit trace" subtitle={`${scopedLogs.length} events for this investigation`} />
              <CardBody className="!p-0">
                <table className="w-full text-left text-[12px]">
                  <thead>
                    <tr className="border-b border-(--color-border) text-[10px] uppercase tracking-wide text-(--color-ink-faint)">
                      <th className="px-4 py-2 font-medium">Time</th>
                      <th className="px-4 py-2 font-medium">Agent</th>
                      <th className="px-4 py-2 font-medium">Tool</th>
                      <th className="px-4 py-2 font-medium">Latency</th>
                      <th className="px-4 py-2 font-medium">Security</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scopedLogs.map((l) => (
                      <tr key={l.id} className="border-b border-(--color-border) last:border-0">
                        <td className="px-4 py-2 font-mono text-(--color-ink-faint)">{new Date(l.timestamp).toLocaleTimeString()}</td>
                        <td className="px-4 py-2 font-medium text-(--color-ink)">{l.agentId}</td>
                        <td className="px-4 py-2 font-mono text-(--color-ink-muted)">{l.toolCall ?? '—'}</td>
                        <td className="px-4 py-2 tabular text-(--color-ink-muted)">{l.latencyMs ? `${l.latencyMs.toFixed(0)}ms` : '—'}</td>
                        <td className="px-4 py-2 text-(--color-ink-muted)">{l.securityDecision ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          </TabsContent>
        </Tabs>
      ) : null}
    </div>
  )
}
