import { ALLOWED_TOOLS_PER_AGENT, TOOL_REGISTRY } from '@/api/demoAdapter/security'
import { Badge } from '@/components/common/Badge'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { LoadingState } from '@/components/common/LoadingState'
import { PromptInjectionDemo } from '@/components/security/PromptInjectionDemo'
import { RBACPanel } from '@/components/security/RBACPanel'
import { useAppState } from '@/state/AppStateContext'
import { useInvestigationByRole } from '@/hooks/useInvestigation'

export function SecurityPage() {
  const { requesterRole } = useAppState()
  const { data: analyst, isLoading } = useInvestigationByRole('ANALYST')
  const { data: executive } = useInvestigationByRole('EXECUTIVE')
  const events = [...(analyst?.securityEvents ?? []), ...(executive?.securityEvents ?? [])]

  return (
    <div className="mx-auto max-w-[1200px] space-y-5 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">System</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Security</h1>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader title="RBAC" subtitle="Requester clearance vs. entitled dimensions" />
          <CardBody>
            <RBACPanel role={requesterRole} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Prompt-injection demonstration" subtitle="Live, client-side classifier mirroring the backend's UNTRUSTED_EVIDENCE boundary" />
          <CardBody>
            <PromptInjectionDemo />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Tool authorization" subtitle="Every agent's allowlist — the ONLY tools it may ever call (src/tools/policy.py)" />
        <CardBody className="!p-0">
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="border-b border-(--color-border) text-[10px] uppercase tracking-wide text-(--color-ink-faint)">
                <th className="px-4 py-2 font-medium">Tool</th>
                <th className="px-4 py-2 font-medium">Classification</th>
                <th className="px-4 py-2 font-medium">Allowed agents</th>
              </tr>
            </thead>
            <tbody>
              {TOOL_REGISTRY.map((t) => (
                <tr key={t.toolName} className="border-b border-(--color-border) last:border-0">
                  <td className="px-4 py-2 font-mono font-medium text-(--color-ink)">{t.toolName}()</td>
                  <td className="px-4 py-2">
                    <Badge tone="neutral">{t.classification}</Badge>
                  </td>
                  <td className="px-4 py-2 text-(--color-ink-muted)">{t.allowedAgents.join(', ')}</td>
                </tr>
              ))}
              <tr>
                <td className="px-4 py-2 font-mono font-medium text-(--color-ink)">ORCHESTRATOR</td>
                <td className="px-4 py-2 text-(--color-ink-faint)">—</td>
                <td className="px-4 py-2 text-(--color-ink-faint)">
                  {ALLOWED_TOOLS_PER_AGENT.ORCHESTRATOR.length === 0 ? 'none — never generates a conclusion' : ALLOWED_TOOLS_PER_AGENT.ORCHESTRATOR.join(', ')}
                </td>
              </tr>
            </tbody>
          </table>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Security events" subtitle="Real events from the two Nov 2017 investigation runs" />
        <CardBody className="space-y-2">
          {isLoading ? (
            <LoadingState />
          ) : events.length === 0 ? (
            <p className="text-[12px] text-(--color-ink-faint)">No security events recorded.</p>
          ) : (
            events.map((e, i) => (
              <div key={i} className="rounded-(--radius-sm) border border-(--color-warning-soft) bg-(--color-warning-soft) px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-[12px] font-bold text-(--color-warning)">{e.type.replaceAll('_', ' ')}</span>
                  {e.agentRole ? <Badge tone="neutral">{e.agentRole}</Badge> : null}
                </div>
                {e.text ? <p className="mt-1 text-[12px] italic text-(--color-ink-muted)">"{e.text}"</p> : null}
                {e.violatingNumbers?.length ? (
                  <p className="mt-0.5 font-mono text-[11px] text-(--color-ink-faint)">
                    flagged: {e.violatingNumbers.join(', ')} — not present in cited evidence, stripped before the claim was accepted
                  </p>
                ) : null}
              </div>
            ))
          )}
        </CardBody>
      </Card>
    </div>
  )
}
