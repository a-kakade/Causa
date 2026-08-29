import type { AuditTraceEntry } from '@/types/investigation'
import { apiFetch } from './client'

export interface LogEntry extends AuditTraceEntry {
  investigationId: string
  requesterRole: 'ANALYST' | 'EXECUTIVE'
}

interface AuditRow {
  agent_id: string
  agent_role: string
  timestamp: string
  tool_call: string | null
  tool_result_ids: string[]
  output: string
  token_usage: number
  latency_ms: number | null
  security_decision: string | null
  investigation_id: string
}

export async function getAllLogs(): Promise<LogEntry[]> {
  const r = await apiFetch<{ entries: AuditRow[] }>('/api/audit')
  return r.entries.map((a, i) => ({
    id: `${a.agent_id}-${i}-${a.timestamp}`, agentId: a.agent_id, agentRole: a.agent_role as LogEntry['agentRole'],
    timestamp: a.timestamp, toolCall: a.tool_call, toolResultIds: a.tool_result_ids, output: a.output,
    tokenUsage: a.token_usage, latencyMs: a.latency_ms, securityDecision: a.security_decision,
    investigationId: a.investigation_id, requesterRole: a.investigation_id.includes('executive') ? 'EXECUTIVE' : 'ANALYST',
  }))
}

export interface LogFilters {
  agentRole?: string
  investigationId?: string
  toolCall?: string
  search?: string
}

export function filterLogs(logs: LogEntry[], filters: LogFilters): LogEntry[] {
  return logs.filter((l) => {
    if (filters.agentRole && l.agentRole !== filters.agentRole) return false
    if (filters.investigationId && l.investigationId !== filters.investigationId) return false
    if (filters.toolCall && l.toolCall !== filters.toolCall) return false
    if (filters.search) {
      const q = filters.search.toLowerCase()
      const hay = `${l.agentId} ${l.toolCall ?? ''} ${l.output} ${l.securityDecision ?? ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}
