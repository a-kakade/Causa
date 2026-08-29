import type {
  AuditTraceEntry,
  ContradictionRecord,
  Hypothesis,
  HypothesisResult,
  InvestigationState,
  SecurityEvent,
  TelemetryRecord,
} from '@/types/investigation'
import { apiFetch, apiPost } from './client'

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

interface RawInvestigation {
  investigation_id: string
  requester_role: string
  kpi_id: string
  period: string
  movement: { absolute: number | null; percentage: number | null; current_value: number | null; previous_value: number | null }
  hypotheses: Array<{
    hypothesis_id: string; statement: string; driver: string; dimension: string; mechanism: string
    expected_evidence: string[]; falsification_evidence: string[]; evidence_types_expected: string[]; status: string
  }>
  contradictions: Array<{
    contradiction_id: string; hypothesis_id: string; supporting_evidence: string[]
    contradicting_evidence: string[]; severity: string; unresolved: boolean
  }>
  hypothesis_results: Array<{
    hypothesis_id: string; status: string; confidence: string; evidence_ids: string[]
    reasons: string[]; method: string | null; contradiction_severity: string
  }>
  confidence: string | null
  status: string
  budgets: Record<string, number>
  audit_trace: Array<{
    agent_id: string; agent_role: string; timestamp: string; tool_call: string | null
    tool_result_ids: string[]; output: string; token_usage: number; latency_ms: number | null; security_decision: string | null
  }>
  telemetry: Array<{
    agent_role: string; model: string | null; input_tokens: number; output_tokens: number; total_tokens: number
    estimated_cost: number; tool_calls: number; retrieval_calls: number; agent_latency_ms: number; total_latency_ms: number
  }>
  security_events: Array<{ type: string; agent_role?: string; field?: string; text?: string; violating_numbers?: number[] }>
  status_history: string[]
}

interface InvestigationResponse {
  investigation_id: string
  requester_role: string
  kpi_id: string
  period_current: string
  period_previous: string
  source: string
  status: string
  created_at: string
  state: RawInvestigation
}

interface ListItem {
  investigation_id: string
  requester_role: string
  kpi_id: string
  status: string
}

function mapInvestigation(raw: RawInvestigation): InvestigationState {
  return {
    investigationId: raw.investigation_id,
    requesterRole: raw.requester_role as InvestigationState['requesterRole'],
    kpiId: raw.kpi_id,
    period: raw.period,
    movement: {
      absolute: raw.movement.absolute ?? Number.NaN,
      percentage: raw.movement.percentage ?? Number.NaN,
      currentValue: raw.movement.current_value ?? Number.NaN,
      previousValue: raw.movement.previous_value ?? Number.NaN,
    },
    hypotheses: raw.hypotheses.map(
      (h): Hypothesis => ({
        hypothesisId: h.hypothesis_id, statement: h.statement, driver: h.driver, dimension: h.dimension,
        mechanism: h.mechanism, expectedEvidence: h.expected_evidence, falsificationEvidence: h.falsification_evidence,
        evidenceTypesExpected: h.evidence_types_expected, status: h.status as Hypothesis['status'],
      }),
    ),
    contradictions: raw.contradictions.map(
      (c): ContradictionRecord => ({
        contradictionId: c.contradiction_id, hypothesisId: c.hypothesis_id, supportingEvidence: c.supporting_evidence,
        contradictingEvidence: c.contradicting_evidence, severity: c.severity as ContradictionRecord['severity'],
        unresolved: c.unresolved,
      }),
    ),
    hypothesisResults: raw.hypothesis_results.map(
      (r): HypothesisResult => ({
        hypothesisId: r.hypothesis_id, status: r.status as HypothesisResult['status'],
        confidence: r.confidence as HypothesisResult['confidence'], evidenceIds: r.evidence_ids, reasons: r.reasons,
        method: r.method ?? '', contradictionSeverity: r.contradiction_severity as HypothesisResult['contradictionSeverity'],
      }),
    ),
    confidence: raw.confidence as InvestigationState['confidence'],
    status: raw.status as InvestigationState['status'],
    budgets: {
      maxIterations: raw.budgets.max_iterations, maxAgentCalls: raw.budgets.max_agent_calls,
      maxToolCalls: raw.budgets.max_tool_calls, maxRetrievalCalls: raw.budgets.max_retrieval_calls,
      maxTokens: raw.budgets.max_tokens, maxLatencySeconds: raw.budgets.max_latency_seconds,
      usedIterations: raw.budgets.used_iterations, usedAgentCalls: raw.budgets.used_agent_calls,
      usedToolCalls: raw.budgets.used_tool_calls, usedRetrievalCalls: raw.budgets.used_retrieval_calls,
    },
    auditTrace: raw.audit_trace.map(
      (a, i): AuditTraceEntry => ({
        id: `${a.agent_id}-${i}-${a.timestamp}`, agentId: a.agent_id, agentRole: a.agent_role as AuditTraceEntry['agentRole'],
        timestamp: a.timestamp, toolCall: a.tool_call, toolResultIds: a.tool_result_ids, output: a.output,
        tokenUsage: a.token_usage, latencyMs: a.latency_ms, securityDecision: a.security_decision,
      }),
    ),
    telemetry: raw.telemetry.map(
      (t): TelemetryRecord => ({
        agentRole: t.agent_role as TelemetryRecord['agentRole'], model: t.model, inputTokens: t.input_tokens,
        outputTokens: t.output_tokens, totalTokens: t.total_tokens, estimatedCost: t.estimated_cost,
        toolCalls: t.tool_calls, retrievalCalls: t.retrieval_calls, agentLatencyMs: t.agent_latency_ms,
        totalLatencyMs: t.total_latency_ms,
      }),
    ),
    securityEvents: raw.security_events.map(
      (s): SecurityEvent => ({
        type: s.type, agentRole: s.agent_role as SecurityEvent['agentRole'], field: s.field, text: s.text,
        violatingNumbers: s.violating_numbers,
      }),
    ),
    statusHistory: raw.status_history,
  }
}

/** Real backend investigations are keyed by investigation_id, not role --
 * this preserves demoAdapter's getInvestigation(role) call-site contract by
 * fetching (or, on first call for a role, creating) that role's most recent
 * investigation via the server's own `?role=&latest=true` convenience query. */
export async function getInvestigation(role: 'ANALYST' | 'EXECUTIVE'): Promise<InvestigationState> {
  const existing = await apiFetch<ListItem[]>(`/api/investigations?role=${role}&latest=true`)
  if (existing.length > 0) {
    const full = await apiFetch<InvestigationResponse>(`/api/investigations/${existing[0].investigation_id}?requester_role=${role}`)
    return mapInvestigation(full.state)
  }
  const created = await apiPost<InvestigationResponse>(`/api/investigations?requester_role=${role}`, {
    kpi_id: 'revenue', period_current: '2017-11', period_previous: '2017-10', mode: 'auto',
  })
  return mapInvestigation(created.state)
}

export async function getCurrentInvestigationId(role: 'ANALYST' | 'EXECUTIVE'): Promise<string> {
  const state = await getInvestigation(role)
  return state.investigationId
}

export async function getTelemetrySummary(role: 'ANALYST' | 'EXECUTIVE'): Promise<TelemetrySummary> {
  const id = await getCurrentInvestigationId(role)
  const r = await apiFetch<{ telemetry_available: boolean } & Partial<TelemetrySummary>>(
    `/api/investigations/${id}/telemetry?requester_role=${role}`,
  )
  return {
    total_llm_calls: r.total_llm_calls ?? 0, total_deterministic_calls: r.total_deterministic_calls ?? 0,
    total_input_tokens: r.total_input_tokens ?? 0, total_output_tokens: r.total_output_tokens ?? 0,
    total_tokens: r.total_tokens ?? 0, total_estimated_cost: r.total_estimated_cost ?? 0,
    total_tool_calls: r.total_tool_calls ?? 0, total_retrieval_calls: r.total_retrieval_calls ?? 0,
    total_agent_latency_ms: r.total_agent_latency_ms ?? 0, by_agent_role: r.by_agent_role ?? {},
  }
}

export interface AskQuestionResult {
  investigationId: string
  kpiId: string
  periodCurrent: string
  periodPrevious: string
  question: string
  resolver: 'openai' | 'keyword'
  state: InvestigationState
}

/** Free-form "ask your own question" entry point. Posts straight text to
 * /api/investigations/ask, which resolves it server-side (src/agents/
 * question_router.py) to a governed {kpi_id, period} pair and runs the same
 * real investigation path the KPI-card flow uses -- this never fabricates
 * an answer client-side. */
export async function askInvestigationQuestion(question: string): Promise<AskQuestionResult> {
  const raw = await apiPost<
    InvestigationResponse & { question: string; resolution: { kpi_id: string; period_current: string; period_previous: string; resolver: 'openai' | 'keyword' } }
  >('/api/investigations/ask', { question })
  return {
    investigationId: raw.investigation_id,
    kpiId: raw.resolution.kpi_id,
    periodCurrent: raw.resolution.period_current,
    periodPrevious: raw.resolution.period_previous,
    question: raw.question,
    resolver: raw.resolution.resolver,
    state: mapInvestigation(raw.state),
  }
}

export async function getRunMeta() {
  return { generatedAt: new Date().toISOString(), llmProvider: 'groq (or replay of a validated real run)', llmModel: 'see /api/investigations/{id}' }
}
