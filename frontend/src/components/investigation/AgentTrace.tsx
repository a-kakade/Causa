import { ArrowDown } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import { formatDuration } from '@/lib/format'
import type { AuditTraceEntry, TelemetryRecord } from '@/types/investigation'

const AGENT_ORDER = ['ORCHESTRATOR', 'HYPOTHESIS', 'EVIDENCE', 'COUNTER_EVIDENCE', 'CAUSAL_SELECTOR', 'CONFIDENCE_JUDGE'] as const

const AGENT_DESCRIPTION: Record<(typeof AGENT_ORDER)[number], string> = {
  ORCHESTRATOR: 'Deterministic — state machine, budgets. Never generates a conclusion.',
  HYPOTHESIS: 'LLM (Groq openai/gpt-oss-20b) — formulates 3-5 hypotheses from governed tools only.',
  EVIDENCE: 'LLM — classifies retrieved evidence SUPPORTS / CONTRADICTS / CONTEXT / INSUFFICIENT.',
  COUNTER_EVIDENCE: 'LLM — adversarial search for evidence against each hypothesis.',
  CAUSAL_SELECTOR: 'Deterministic — selects only T1/T2 methods, never T3/T4.',
  CONFIDENCE_JUDGE: 'Deterministic — scores HIGH/MEDIUM/LOW/ABSTAIN; can only downgrade an LLM claim, never upgrade.',
}

// Agent architecture classification (docs/MULTI_AGENT_ARCHITECTURE.md) — fixed
// by design, not inferred from telemetry. The backend labels every agent's
// telemetry record with a `model` string (even deterministic ones get
// "deterministic_rule_engine_v1"), so `model != null` is NOT a reliable
// signal for "is this an LLM agent".
const IS_LLM_AGENT: Record<(typeof AGENT_ORDER)[number], boolean> = {
  ORCHESTRATOR: false,
  HYPOTHESIS: true,
  EVIDENCE: true,
  COUNTER_EVIDENCE: true,
  CAUSAL_SELECTOR: false,
  CONFIDENCE_JUDGE: false,
}

export function AgentTrace({ auditTrace, telemetry }: { auditTrace: AuditTraceEntry[]; telemetry: TelemetryRecord[] }) {
  return (
    <div className="space-y-1">
      {AGENT_ORDER.map((role, i) => {
        const entries = auditTrace.filter((e) => e.agentRole === role)
        const tel = telemetry.filter((t) => t.agentRole === role)
        // Invocations = telemetry entries (every agent call gets one, even
        // deterministic ones with no tool call). Tool calls are the subset
        // of audit_trace entries that actually invoked the Tool Gateway.
        const calls = tel.length
        const totalLatency = tel.reduce((n, t) => n + t.agentLatencyMs, 0)
        const totalTokens = tel.reduce((n, t) => n + t.totalTokens, 0)
        const toolCalls = entries.filter((e) => e.toolCall).map((e) => e.toolCall as string)
        const uniqueTools = [...new Set(toolCalls)]
        const evidenceIds = [...new Set(entries.flatMap((e) => e.toolResultIds))]
        const isLlm = IS_LLM_AGENT[role]
        const ran = calls > 0 || entries.length > 0

        return (
          <div key={role}>
            <div className={`rounded-(--radius-md) border p-3 ${ran ? 'border-(--color-border)' : 'border-dashed border-(--color-border) opacity-60'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12px] font-bold text-(--color-ink)">{role.replaceAll('_', ' ')}</span>
                  <Badge tone={isLlm ? 'accent' : 'neutral'}>{isLlm ? 'LLM agent' : 'Deterministic'}</Badge>
                  <Badge tone={ran ? 'positive' : 'neutral'}>{ran ? 'Ran' : 'Not invoked'}</Badge>
                </div>
                {ran ? (
                  <span className="font-mono text-[11px] text-(--color-ink-faint)">
                    {calls} call{calls === 1 ? '' : 's'} · {formatDuration(totalLatency)}
                    {totalTokens ? ` · ${totalTokens.toLocaleString()} tok` : ''}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-[11px] text-(--color-ink-faint)">{AGENT_DESCRIPTION[role]}</p>
              {uniqueTools.length ? (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {uniqueTools.map((t) => (
                    <span key={t} className="rounded-(--radius-xs) bg-(--color-surface-2) px-1.5 py-0.5 font-mono text-[10px] text-(--color-ink-muted)">
                      {t}()
                    </span>
                  ))}
                </div>
              ) : null}
              {evidenceIds.length ? (
                <p className="mt-1.5 truncate font-mono text-[10px] text-(--color-ink-faint)">{evidenceIds.length} evidence id(s) touched</p>
              ) : null}
            </div>
            {i < AGENT_ORDER.length - 1 ? (
              <div className="flex justify-center py-0.5">
                <ArrowDown className="size-3 text-(--color-ink-faint)" />
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
