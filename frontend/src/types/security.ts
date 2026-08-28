import type { AgentRole, RequesterRole, SecurityClassification } from './common'

/** Hand-ported (values only) from causa/src/tools/policy.py — the real RBAC
 * tables the Tool Gateway checks before any tool executes. */
export interface RBACClearanceTable {
  [role: string]: SecurityClassification
}

export interface ToolPermissionTable {
  [agentRole: string]: readonly string[]
}

export interface ToolDefinition {
  toolName: string
  allowedAgents: AgentRole[]
  classification: SecurityClassification
  description: string
}

export interface PromptInjectionFixture {
  fixtureId: string
  text: string
}

export interface PromptInjectionDemoResult {
  fixtureId: string
  sourceText: string
  source: 'Customer Review'
  classification: 'UNTRUSTED_SOURCE_TEXT'
  detected: string[]
  action: 'BLOCKED'
  toolExecution: 'NONE'
  dataDisclosure: 'NONE'
}

export interface RBACDemoResult {
  requesterRole: RequesterRole
  requestedClassification: SecurityClassification
  requesterClearance: SecurityClassification
  decision: 'ALLOWED' | 'DENIED'
  reason: string
}
