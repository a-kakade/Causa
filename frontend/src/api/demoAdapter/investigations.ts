import type {
  AuditTraceEntry,
  ContradictionRecord,
  Hypothesis,
  HypothesisResult,
  InvestigationState,
  SecurityEvent,
  TelemetryRecord,
} from '@/types/investigation'
import { loadFixture } from './loadFixture'

type RawRole = 'analyst_investigation' | 'executive_investigation'

interface RawInvestigation {
  investigation_id: string
  requester_role: string
  kpi_id: string
  period: string
  movement: { absolute: number; percentage: number; current_value: number; previous_value: number }
  hypotheses: {
    hypothesis_id: string
    statement: string
    driver: string
    dimension: string
    mechanism: string
    expected_evidence: string[]
    falsification_evidence: string[]
    evidence_types_expected: string[]
    status: string
  }[]
  contradictions: {
    contradiction_id: string
    hypothesis_id: string
    supporting_evidence: string[]
    contradicting_evidence: string[]
    severity: string
    unresolved: boolean
  }[]
  hypothesis_results: {
    hypothesis_id: string
    status: string
    confidence: string
    evidence_ids: string[]
    reasons: string[]
    method: string
    contradiction_severity: string
  }[]
  confidence: string | null
  status: string
  budgets: {
    max_iterations: number
    max_agent_calls: number
    max_tool_calls: number
    max_retrieval_calls: number
    max_tokens: number
    max_latency_seconds: number
    used_iterations: number
    used_agent_calls: number
    used_tool_calls: number
    used_retrieval_calls: number
  }
  audit_trace: {
    agent_id: string
    agent_role: string
    timestamp: string
    tool_call: string | null
    tool_result_ids: string[]
    output: string
    token_usage: number
    latency_ms: number | null
    security_decision: string | null
  }[]
  telemetry: {
    agent_role: string
    model: string | null
    input_tokens: number
    output_tokens: number
    total_tokens: number
    estimated_cost: number
    tool_calls: number
    retrieval_calls: number
    agent_latency_ms: number
    total_latency_ms: number
  }[]
  security_events: { type: string; agent_role?: string; field?: string; text?: string; violating_numbers?: number[] }[]
  status_history: string[]
}

interface Step5Report {
  generated_at: string
  llm_provider: string
  llm_model: string
  analyst_investigation: RawInvestigation
  executive_investigation: RawInvestigation
  analyst_telemetry_summary: TelemetrySummary
  executive_telemetry_summary: TelemetrySummary
}

export interface TelemetrySummary {
  total_llm_calls: number
  total_deterministic_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_estimated_cost: number
  total_tool_calls: number
  total_retrieval_calls: number
  total_agent_latency_ms: number
  by_agent_role: Record<string, { calls: number; tokens?: number; latency_ms?: number; cost?: number }>
}

function mapInvestigation(raw: RawInvestigation): InvestigationState {
  const hypotheses: Hypothesis[] = raw.hypotheses.map((h) => ({
    hypothesisId: h.hypothesis_id,
    statement: h.statement,
    driver: h.driver,
    dimension: h.dimension,
    mechanism: h.mechanism,
    expectedEvidence: h.expected_evidence,
    falsificationEvidence: h.falsification_evidence,
    evidenceTypesExpected: h.evidence_types_expected,
    status: h.status as Hypothesis['status'],
  }))

  const contradictions: ContradictionRecord[] = raw.contradictions.map((c) => ({
    contradictionId: c.contradiction_id,
    hypothesisId: c.hypothesis_id,
    supportingEvidence: c.supporting_evidence,
    contradictingEvidence: c.contradicting_evidence,
    severity: c.severity as ContradictionRecord['severity'],
    unresolved: c.unresolved,
  }))

  const hypothesisResults: HypothesisResult[] = raw.hypothesis_results.map((r) => ({
    hypothesisId: r.hypothesis_id,
    status: r.status as HypothesisResult['status'],
    confidence: r.confidence as HypothesisResult['confidence'],
    evidenceIds: r.evidence_ids,
    reasons: r.reasons,
    method: r.method,
    contradictionSeverity: r.contradiction_severity as HypothesisResult['contradictionSeverity'],
  }))

  const auditTrace: AuditTraceEntry[] = raw.audit_trace.map((a, i) => ({
    id: `${a.agent_id}-${i}-${a.timestamp}`,
    agentId: a.agent_id,
    agentRole: a.agent_role as AuditTraceEntry['agentRole'],
    timestamp: a.timestamp,
    toolCall: a.tool_call,
    toolResultIds: a.tool_result_ids,
    output: a.output,
    tokenUsage: a.token_usage,
    latencyMs: a.latency_ms,
    securityDecision: a.security_decision,
  }))

  const telemetry: TelemetryRecord[] = raw.telemetry.map((t) => ({
    agentRole: t.agent_role as TelemetryRecord['agentRole'],
    model: t.model,
    inputTokens: t.input_tokens,
    outputTokens: t.output_tokens,
    totalTokens: t.total_tokens,
    estimatedCost: t.estimated_cost,
    toolCalls: t.tool_calls,
    retrievalCalls: t.retrieval_calls,
    agentLatencyMs: t.agent_latency_ms,
    totalLatencyMs: t.total_latency_ms,
  }))

  const securityEvents: SecurityEvent[] = raw.security_events.map((s) => ({
    type: s.type,
    agentRole: s.agent_role as SecurityEvent['agentRole'],
    field: s.field,
    text: s.text,
    violatingNumbers: s.violating_numbers,
  }))

  return {
    investigationId: raw.investigation_id,
    requesterRole: raw.requester_role as InvestigationState['requesterRole'],
    kpiId: raw.kpi_id,
    period: raw.period,
    movement: {
      absolute: raw.movement.absolute,
      percentage: raw.movement.percentage,
      currentValue: raw.movement.current_value,
      previousValue: raw.movement.previous_value,
    },
    hypotheses,
    contradictions,
    hypothesisResults,
    confidence: raw.confidence as InvestigationState['confidence'],
    status: raw.status as InvestigationState['status'],
    budgets: {
      maxIterations: raw.budgets.max_iterations,
      maxAgentCalls: raw.budgets.max_agent_calls,
      maxToolCalls: raw.budgets.max_tool_calls,
      maxRetrievalCalls: raw.budgets.max_retrieval_calls,
      maxTokens: raw.budgets.max_tokens,
      maxLatencySeconds: raw.budgets.max_latency_seconds,
      usedIterations: raw.budgets.used_iterations,
      usedAgentCalls: raw.budgets.used_agent_calls,
      usedToolCalls: raw.budgets.used_tool_calls,
      usedRetrievalCalls: raw.budgets.used_retrieval_calls,
    },
    auditTrace,
    telemetry,
    securityEvents,
    statusHistory: raw.status_history,
  }
}

let cached: Step5Report | null = null
async function report(): Promise<Step5Report> {
  if (!cached) cached = await loadFixture<Step5Report>('step5_validation')
  return cached
}

export async function getInvestigation(role: 'ANALYST' | 'EXECUTIVE'): Promise<InvestigationState> {
  const r = await report()
  const key: RawRole = role === 'ANALYST' ? 'analyst_investigation' : 'executive_investigation'
  return mapInvestigation(r[key])
}

export async function getTelemetrySummary(role: 'ANALYST' | 'EXECUTIVE'): Promise<TelemetrySummary> {
  const r = await report()
  return role === 'ANALYST' ? r.analyst_telemetry_summary : r.executive_telemetry_summary
}

export async function getRunMeta() {
  const r = await report()
  return { generatedAt: r.generated_at, llmProvider: r.llm_provider, llmModel: r.llm_model }
}
