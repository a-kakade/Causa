import type { AuditTraceEntry } from '@/types/investigation'
import { getInvestigation } from './investigations'

export interface LogEntry extends AuditTraceEntry {
  investigationId: string
  requesterRole: 'ANALYST' | 'EXECUTIVE'
}

export async function getAllLogs(): Promise<LogEntry[]> {
  const [analyst, executive] = await Promise.all([getInvestigation('ANALYST'), getInvestigation('EXECUTIVE')])
  const fromRun = (inv: typeof analyst, role: 'ANALYST' | 'EXECUTIVE'): LogEntry[] =>
    inv.auditTrace.map((e) => ({ ...e, investigationId: inv.investigationId, requesterRole: role }))
  return [...fromRun(analyst, 'ANALYST'), ...fromRun(executive, 'EXECUTIVE')].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
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
