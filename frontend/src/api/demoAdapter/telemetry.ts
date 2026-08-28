import { getRunMeta, getTelemetrySummary } from './investigations'

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
}

export async function getTelemetryView(role: 'ANALYST' | 'EXECUTIVE'): Promise<TelemetryView> {
  const [summary, runMeta] = await Promise.all([getTelemetrySummary(role), getRunMeta()])
  const byAgentRole: AgentMetric[] = Object.entries(summary.by_agent_role).map(([agentRole, v]) => ({
    agentRole,
    calls: v.calls,
    tokens: v.tokens ?? 0,
    cost: v.cost ?? 0,
  }))
  // Retrieval calls are the only cache-relevant tool in this pipeline (the
  // embedding cache backs search_evidence) — the report doesn't break out a
  // hit/miss count, so we surface the retrieval call count itself rather
  // than inventing a hit rate.
  return {
    runMeta,
    role,
    totalLatencyMs: summary.total_agent_latency_ms,
    totalTokens: summary.total_tokens,
    totalCost: summary.total_estimated_cost,
    llmCalls: summary.total_llm_calls,
    deterministicCalls: summary.total_deterministic_calls,
    toolCalls: summary.total_tool_calls,
    retrievalCalls: summary.total_retrieval_calls,
    cacheHits: 0,
    cacheMisses: 0,
    byAgentRole,
  }
}
