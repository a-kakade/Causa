import { useState } from 'react'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { LoadingState } from '@/components/common/LoadingState'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/common/Tabs'
import { useTelemetryView } from '@/hooks/useTelemetry'
import { formatDuration } from '@/lib/format'

export function TelemetryPage() {
  const [role, setRole] = useState<'ANALYST' | 'EXECUTIVE'>('ANALYST')
  const { data, isLoading } = useTelemetryView(role)

  return (
    <div className="mx-auto max-w-[1200px] space-y-5 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">System</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Telemetry</h1>
      </div>

      <Tabs value={role} onValueChange={(v) => setRole(v as 'ANALYST' | 'EXECUTIVE')}>
        <TabsList>
          <TabsTrigger value="ANALYST">Analyst run</TabsTrigger>
          <TabsTrigger value="EXECUTIVE">Executive run</TabsTrigger>
        </TabsList>
        <TabsContent value={role} className="mt-4 space-y-4">
          {isLoading || !data ? (
            <LoadingState label="Loading telemetry" />
          ) : (
            <>
              <div className="text-[11px] text-(--color-ink-faint)">
                {data.runMeta.llmProvider} · {data.runMeta.llmModel} · generated {new Date(data.runMeta.generatedAt).toLocaleString()}
              </div>
              <div className="grid grid-cols-5 gap-3">
                <Stat label="Total agent latency" value={formatDuration(data.totalLatencyMs)} />
                <Stat label="LLM calls" value={String(data.llmCalls)} />
                <Stat label="Deterministic calls" value={String(data.deterministicCalls)} />
                <Stat label="Tool calls" value={String(data.toolCalls)} />
                <Stat label="Tokens" value={data.totalTokens.toLocaleString()} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Retrieval calls" value={String(data.retrievalCalls)} />
                <Stat label="Estimated cost" value={`$${data.totalCost.toFixed(4)}`} />
              </div>

              <Card>
                <CardHeader title="By agent role" subtitle="Real per-agent call counts, tokens, and cost from the Step 5 run" />
                <CardBody className="!p-0">
                  <table className="w-full text-left text-[12px]">
                    <thead>
                      <tr className="border-b border-(--color-border) text-[10px] uppercase tracking-wide text-(--color-ink-faint)">
                        <th className="px-4 py-2 font-medium">Agent</th>
                        <th className="px-4 py-2 font-medium">Calls</th>
                        <th className="px-4 py-2 font-medium">Tokens</th>
                        <th className="px-4 py-2 font-medium">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.byAgentRole.map((a) => (
                        <tr key={a.agentRole} className="border-b border-(--color-border) last:border-0">
                          <td className="px-4 py-2 font-mono font-medium text-(--color-ink)">{a.agentRole}</td>
                          <td className="px-4 py-2 tabular text-(--color-ink-muted)">{a.calls}</td>
                          <td className="px-4 py-2 tabular text-(--color-ink-muted)">{a.tokens.toLocaleString()}</td>
                          <td className="px-4 py-2 tabular text-(--color-ink-muted)">${a.cost.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardBody>
              </Card>
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-(--radius-md) border border-(--color-border) bg-(--color-surface) p-3">
      <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{label}</p>
      <p className="text-lg font-bold tabular text-(--color-ink)">{value}</p>
    </div>
  )
}
