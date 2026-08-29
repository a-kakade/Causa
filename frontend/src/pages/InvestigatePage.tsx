import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { kpiDef } from '@/api'
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
import { useCreateInvestigation, useCurrentInvestigation } from '@/hooks/useInvestigation'
import { useKpiMovement } from '@/hooks/useKpis'
import { useAllLogs } from '@/hooks/useLogs'
import { useAppState } from '@/state/AppStateContext'
import { formatKpiValue } from '@/lib/format'
import type { RequesterRole } from '@/types/common'

function runFor(role: RequesterRole): 'ANALYST' | 'EXECUTIVE' {
  return role === 'EXECUTIVE' ? 'EXECUTIVE' : 'ANALYST'
}

export function InvestigatePage() {
  const { kpiId = 'revenue' } = useParams()
  const [params] = useSearchParams()
  const initialTab = params.get('tab') ?? 'overview'
  const [tab, setTab] = useState(initialTab)
  const [liveMode, setLiveMode] = useState(false)
  const [revealed, setRevealed] = useState(true)

  const def = kpiDef(kpiId)
  const { data: movement, isLoading: loadingMovement } = useKpiMovement(kpiId)
  const { requesterRole, endPeriod, previousEndPeriod } = useAppState()
  const role = runFor(requesterRole)

  const { data: decomposition } = useDriverDecomposition()
  const { data: concurrent } = useConcurrentKpiMovements()
  const { data: investigation } = useCurrentInvestigation(kpiId)
  const { data: causalResults } = useCausalResults()
  const { data: contradictionChecks } = useContradictionChecks()
  const { data: logs } = useAllLogs()
  const createInvestigation = useCreateInvestigation()

  if (!def) return <ErrorState title="Unknown KPI" message={`No governed KPI contract for "${kpiId}".`} />
  if (loadingMovement || !movement) return <LoadingState label="Loading KPI movement" />

  // investigation != null alone signals a real investigation has run for
  // this (role, kpiId, period) -- not investigation.hypotheses.length > 0,
  // since a legitimate real run can abstain with zero hypotheses generated
  // (e.g. the canonical revenue/Nov-2017 fixture) and that's still a real
  // result, not an "hasn't been run yet" state. The kpiId check guards
  // against demoAdapter's fallback: when Demo mode has no baked scenario for
  // the requested KPI/period, getInvestigation() hands back the one
  // canonical Revenue/Nov-2017 investigation regardless of what was asked
  // for -- without this check, an Orders page would render hypotheses that
  // literally talk about "revenue rise" under an Orders header. Live mode
  // never mismatches (the backend always creates/returns a real investigation
  // scoped to the requested kpiId), so this is a no-op there.
  const hasInvestigation = investigation != null && investigation.kpiId === kpiId
  // PVM decomposition, counter-evidence/contradiction checks, and the causal
  // (T1-T4) analysis panel are still backed by revenue-only endpoints in
  // this build (see api/productionApi/drivers.ts, evidence.ts, causal.ts) --
  // unlike the Confidence/Hypotheses panels above, which now run a real,
  // per-KPI investigation via useCurrentInvestigation.
  const isRevenue = kpiId === 'revenue'
  const scopedLogs = (logs ?? []).filter((l) => l.investigationId === investigation?.investigationId)

  function handleInvestigate(mode?: 'auto' | 'live' | 'fresh') {
    setRevealed(false)
    // Mount the live panel immediately, before the mutation resolves --
    // a real run can take anywhere from under a second to several minutes
    // (mode=live makes genuine Groq round-trips), so the panel needs to be
    // showing real elapsed time from the moment the call starts, not just
    // played back as a fixed-length animation once the result is already in.
    setLiveMode(true)
    createInvestigation.mutate(
      { role, kpiId, periodCurrent: endPeriod, periodPrevious: previousEndPeriod, mode },
      { onError: () => { setLiveMode(false); setRevealed(true) } },
    )
  }

  // "Investigate further" (from the abstained/leading-candidates view) has
  // to bypass the canonical Revenue/Nov-2017 replay path -- mode='auto'
  // there just plays back the same cached reports/step5_validation.json
  // every time, so a re-run would look frozen. mode='fresh' forces a real,
  // non-replayed pipeline run instead (see api/routes/investigations.py).
  function handleInvestigateFresh() {
    handleInvestigate('fresh')
  }

  return (
    <div className="mx-auto max-w-[1400px]">
      <InvestigationHeader
        def={def}
        movement={movement}
        investigationStatus={hasInvestigation ? investigation?.status : undefined}
        investigation={hasInvestigation ? investigation : undefined}
        onInvestigate={() => handleInvestigate()}
      />

      {liveMode ? (
        <div className="px-6 pt-4">
          <LiveInvestigationPanel
            hypotheses={investigation?.hypotheses ?? []}
            kpiName={def.name}
            pending={createInvestigation.isPending}
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
                <CardHeader title="What changed" subtitle={`${formatKpiValue(movement.previousValue, def.unit)} → ${formatKpiValue(movement.currentValue, def.unit)}`} />
                <CardBody>
                  <KPITrend kpiId={kpiId} valueFormatter={(v) => formatKpiValue(v, def.unit)} />
                </CardBody>
              </Card>
              <Card>
                <CardHeader
                  title="Confidence"
                  subtitle={hasInvestigation ? (isRevenue ? 'From the real Step 5 agent run' : 'From a real investigation run') : 'No investigation run for this KPI yet'}
                />
                <CardBody>
                  {hasInvestigation && investigation ? (
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
                  {hasInvestigation && investigation ? (
                    investigation.status === 'ABSTAINED' ? (
                      <AbstentionState
                        hypotheses={investigation.hypotheses}
                        results={investigation.hypothesisResults}
                        contradictions={investigation.contradictions}
                        reasons={[
                          'Additional evidence retrieval rounds for this KPI/period',
                          'Segment-level evidence beyond the concurrent-KPI signals already gathered',
                        ]}
                        kpiName={def.name}
                        onInvestigateFurther={handleInvestigateFresh}
                        investigateFurtherPending={createInvestigation.isPending}
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
