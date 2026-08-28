import type { AgentRole, ConfidenceLevel, RequesterRole } from './common'

/** Mirrors src/agents/models.py::Hypothesis */
export interface Hypothesis {
  hypothesisId: string
  statement: string
  driver: string
  dimension: string
  mechanism: string
  expectedEvidence: string[]
  falsificationEvidence: string[]
  evidenceTypesExpected: string[]
  status: 'PROPOSED' | 'TESTED'
}

export type HypothesisStatus =
  | 'SUPPORTED'
  | 'PARTIALLY_SUPPORTED'
  | 'CONTRADICTED'
  | 'UNRESOLVED'
  | 'REJECTED'
  | 'INCONCLUSIVE'

/** Mirrors src/agents/models.py::HypothesisResult */
export interface HypothesisResult {
  hypothesisId: string
  status: HypothesisStatus
  confidence: ConfidenceLevel
  evidenceIds: string[]
  reasons: string[]
  method: string
  contradictionSeverity: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
}

export interface ContradictionRecord {
  contradictionId: string
  hypothesisId: string
  supportingEvidence: string[]
  contradictingEvidence: string[]
  severity: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
  unresolved: boolean
}

/** Mirrors src/agents/models.py::AuditTraceEntry — the process-proof timeline. */
export interface AuditTraceEntry {
  id: string
  agentId: string
  agentRole: AgentRole | 'ORCHESTRATOR'
  timestamp: string
  toolCall: string | null
  toolResultIds: string[]
  output: string
  tokenUsage: number
  latencyMs: number | null
  securityDecision: string | null
}

/** Mirrors src/agents/models.py::TelemetryRecord */
export interface TelemetryRecord {
  agentRole: AgentRole
  model: string | null
  inputTokens: number
  outputTokens: number
  totalTokens: number
  estimatedCost: number
  toolCalls: number
  retrievalCalls: number
  agentLatencyMs: number
  totalLatencyMs: number
}

/** Real security events are heterogeneous (e.g. the analyst run's actual
 * NUMERIC_VALIDATION_FAILED events, where the Hypothesis agent's guardrail
 * caught an unattributed number in a statement and stripped it). Kept
 * loose/typed-by-`type` rather than a closed enum so we render exactly what
 * the backend recorded instead of forcing it into an invented taxonomy. */
export interface SecurityEvent {
  type: string
  agentRole?: AgentRole
  field?: string
  text?: string
  violatingNumbers?: number[]
}

export type InvestigationStatus =
  | 'PLANNED'
  | 'SECURITY_VALIDATED'
  | 'HYPOTHESES_GENERATED'
  | 'EVIDENCE_COLLECTION'
  | 'COUNTER_EVIDENCE'
  | 'CONTRADICTION_ANALYSIS'
  | 'METHOD_SELECTION'
  | 'CONFIDENCE_EVALUATION'
  | 'COMPLETED'
  | 'ABSTAINED'
  | 'NEEDS_CLARIFICATION'
  | 'BUDGET_EXCEEDED'
  | 'SECURITY_BLOCKED'

export interface InvestigationBudgets {
  maxIterations: number
  maxAgentCalls: number
  maxToolCalls: number
  maxRetrievalCalls: number
  maxTokens: number
  maxLatencySeconds: number
  usedIterations: number
  usedAgentCalls: number
  usedToolCalls: number
  usedRetrievalCalls: number
}

/** Mirrors src/agents/models.py::InvestigationState — the single place
 * investigation progress lives on the backend. */
export interface InvestigationState {
  investigationId: string
  requesterRole: RequesterRole
  kpiId: string
  period: string
  movement: {
    absolute: number
    percentage: number
    currentValue: number
    previousValue: number
  }
  hypotheses: Hypothesis[]
  contradictions: ContradictionRecord[]
  hypothesisResults: HypothesisResult[]
  confidence: ConfidenceLevel | null
  status: InvestigationStatus
  budgets: InvestigationBudgets
  auditTrace: AuditTraceEntry[]
  telemetry: TelemetryRecord[]
  securityEvents: SecurityEvent[]
  /** Raw strings as the backend recorded them — the terminal entry often
   * carries an explanatory suffix, e.g. "ABSTAINED (confidence judge
   * abstained on every hypothesis)". */
  statusHistory: string[]
}
