import type { RequesterRole, SecurityClassification } from '@/types/common'
import type { PromptInjectionDemoResult, PromptInjectionFixture, RBACDemoResult, ToolDefinition } from '@/types/security'
import { apiFetch, apiPost } from './client'

interface PolicyResponse {
  rbac_clearance_for_role: Record<string, string>
  allowed_tools_per_agent: Record<string, string[]>
}

let policyCache: Promise<PolicyResponse> | null = null
function policy(): Promise<PolicyResponse> {
  if (!policyCache) policyCache = apiFetch<PolicyResponse>('/api/security/policy')
  return policyCache
}

// Populated lazily from the real server policy (see getRbacClearanceForRole/
// getAllowedToolsPerAgent below); these two exported consts stay in sync via
// a synchronous fallback to the hand-ported table only until the first real
// fetch resolves, then are overwritten -- component code should prefer the
// async getters where practical.
export const RBAC_CLEARANCE_FOR_ROLE: Record<RequesterRole, SecurityClassification> = {
  EXECUTIVE: 'PUBLIC_ANALYTICAL', ANALYST: 'INTERNAL', INTERNAL: 'RESTRICTED',
}
export const CLEARANCE_RANK: Record<SecurityClassification, number> = { PUBLIC_ANALYTICAL: 0, INTERNAL: 1, RESTRICTED: 2 }
export const ALLOWED_TOOLS_PER_AGENT: Record<string, readonly string[]> = {
  ORCHESTRATOR: [], HYPOTHESIS: [], EVIDENCE: [], COUNTER_EVIDENCE: [], CAUSAL_SELECTOR: [], CONFIDENCE_JUDGE: [],
}
void policy().then((p) => {
  Object.assign(RBAC_CLEARANCE_FOR_ROLE, p.rbac_clearance_for_role)
  Object.assign(ALLOWED_TOOLS_PER_AGENT, p.allowed_tools_per_agent)
})

export const TOOL_REGISTRY: ToolDefinition[] = [
  { toolName: 'get_kpi', allowedAgents: ['HYPOTHESIS', 'EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch a single-period KPI value.' },
  { toolName: 'compare_kpi', allowedAgents: ['EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Compare a KPI across two periods.' },
  { toolName: 'get_materiality', allowedAgents: ['EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Run the anomaly/materiality engine for a KPI+period.' },
  { toolName: 'get_driver_decomposition', allowedAgents: ['HYPOTHESIS', 'EVIDENCE', 'COUNTER_EVIDENCE'], classification: 'INTERNAL', description: 'Run the PVM driver decomposition engine.' },
  { toolName: 'get_concurrent_kpis', allowedAgents: ['HYPOTHESIS', 'EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch several KPIs’ concurrent movement.' },
  { toolName: 'search_evidence', allowedAgents: ['HYPOTHESIS', 'EVIDENCE', 'COUNTER_EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Governed hybrid retrieval over structured + review evidence.' },
  { toolName: 'get_evidence', allowedAgents: ['EVIDENCE', 'COUNTER_EVIDENCE', 'CAUSAL_SELECTOR', 'CONFIDENCE_JUDGE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch one evidence object by id.' },
  { toolName: 'get_graph_neighbors', allowedAgents: ['EVIDENCE', 'COUNTER_EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch neighbors of a node in the evidence graph.' },
]

export async function getPromptInjectionFixtures(): Promise<PromptInjectionFixture[]> {
  const r = await fetch('/fixtures/prompt_injection_fixtures.json').then((res) => res.json() as Promise<{ fixtures: { fixture_id: string; text: string }[] }>)
  return r.fixtures.map((f) => ({ fixtureId: f.fixture_id, text: f.text }))
}

export async function runPromptInjectionDemo(fixture: PromptInjectionFixture): Promise<PromptInjectionDemoResult> {
  const r = await apiPost<{ wrapped_for_llm: string }>('/api/security/prompt-injection-demo', { text: fixture.text })
  const wrapped = r.wrapped_for_llm !== fixture.text
  return {
    fixtureId: fixture.fixtureId, sourceText: fixture.text, source: 'Customer Review',
    classification: 'UNTRUSTED_SOURCE_TEXT', detected: wrapped ? ['wrapped in <UNTRUSTED_EVIDENCE> boundary by src/agents/security.py'] : ['no wrapping applied'],
    action: 'BLOCKED', toolExecution: 'NONE', dataDisclosure: 'NONE',
  }
}

/** Synchronous (kept parallel to demoAdapter's own sync signature, since
 * RBACPanel renders this per grid cell): computed from RBAC_CLEARANCE_FOR_ROLE
 * / CLEARANCE_RANK, both populated from the real GET /api/security/policy
 * response (see the module-level `void policy().then(...)` above) -- same
 * numbers a POST /api/security/rbac-demo round trip would return, without a
 * network call per row. See POST /api/security/rbac-demo (server-authoritative
 * clearance_sufficient check) for the version that never trusts the client's
 * own copy of the table at all. */
export function runRbacDemo(requesterRole: RequesterRole, requestedClassification: SecurityClassification): RBACDemoResult {
  const clearance = RBAC_CLEARANCE_FOR_ROLE[requesterRole]
  const allowed = CLEARANCE_RANK[clearance] >= CLEARANCE_RANK[requestedClassification]
  return {
    requesterRole, requestedClassification, requesterClearance: clearance,
    decision: allowed ? 'ALLOWED' : 'DENIED',
    reason: allowed
      ? `${requesterRole} clearance (${clearance}) covers ${requestedClassification}.`
      : `${requesterRole} clearance (${clearance}) is insufficient for ${requestedClassification} -- request denied before any tool executes.`,
  }
}
