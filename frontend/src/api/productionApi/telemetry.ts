import { apiFetch } from './client'
import { getCurrentInvestigationId, getRunMeta } from './investigations'

export interface AgentMetric {
  agentRole: string
  calls: number
  tokens: number
  cost: number
}

export interface TelemetryView {
  runMeta: { generatedAt: string; llmProvider: string; llmModel: string }
  role: 'ANALYST' | 'EXECUTIVE'
  totalLatencyMs: number
  totalTokens: number
  totalCost: number
  llmCalls: number
  deterministicCalls: number
  toolCalls: number
  retrievalCalls: number
  cacheHits: number
  cacheMisses: number
  byAgentRole: AgentMetric[]
  telemetryAvailable: boolean
}

interface TelemetryResponse {
  telemetry_available: boolean
  total_agent_latency_ms?: number
  total_tokens?: number
  total_estimated_cost?: number
  total_llm_calls?: number
  total_deterministic_calls?: number
  total_tool_calls?: number
  total_retrieval_calls?: number
  by_agent_role?: Record<string, { calls: number; tokens?: number; cost?: number }>
}

export async function getTelemetryView(role: 'ANALYST' | 'EXECUTIVE'): Promise<TelemetryView> {
  const [id, runMeta] = await Promise.all([getCurrentInvestigationId(role), getRunMeta()])
  const r = await apiFetch<TelemetryResponse>(`/api/investigations/${id}/telemetry?requester_role=${role}`)
  const byAgentRole: AgentMetric[] = Object.entries(r.by_agent_role ?? {}).map(([agentRole, v]) => ({
    agentRole, calls: v.calls, tokens: v.tokens ?? 0, cost: v.cost ?? 0,
  }))
  return {
    runMeta, role, telemetryAvailable: r.telemetry_available,
    totalLatencyMs: r.total_agent_latency_ms ?? 0, totalTokens: r.total_tokens ?? 0, totalCost: r.total_estimated_cost ?? 0,
    llmCalls: r.total_llm_calls ?? 0, deterministicCalls: r.total_deterministic_calls ?? 0,
    toolCalls: r.total_tool_calls ?? 0, retrievalCalls: r.total_retrieval_calls ?? 0,
    cacheHits: 0, cacheMisses: 0, byAgentRole,
  }
}
