import type { RequesterRole, SecurityClassification } from '@/types/common'
import type { PromptInjectionDemoResult, PromptInjectionFixture, RBACDemoResult, ToolDefinition } from '@/types/security'
import { loadFixture } from './loadFixture'

/** Hand-ported (values only) from causa/src/tools/policy.py::RBAC_CLEARANCE_FOR_ROLE.
 * Reused verbatim — never a parallel/invented scale. */
export const RBAC_CLEARANCE_FOR_ROLE: Record<RequesterRole, SecurityClassification> = {
  EXECUTIVE: 'PUBLIC_ANALYTICAL',
  ANALYST: 'INTERNAL',
  INTERNAL: 'RESTRICTED',
}

export const CLEARANCE_RANK: Record<SecurityClassification, number> = {
  PUBLIC_ANALYTICAL: 0,
  INTERNAL: 1,
  RESTRICTED: 2,
}

/** Hand-ported from causa/src/tools/policy.py::ALLOWED_TOOLS_PER_AGENT. */
export const ALLOWED_TOOLS_PER_AGENT: Record<string, readonly string[]> = {
  ORCHESTRATOR: [],
  HYPOTHESIS: ['get_kpi', 'get_driver_decomposition', 'get_concurrent_kpis', 'search_evidence'],
  EVIDENCE: [
    'get_kpi',
    'compare_kpi',
    'get_materiality',
    'get_driver_decomposition',
    'get_concurrent_kpis',
    'search_evidence',
    'get_evidence',
    'get_graph_neighbors',
  ],
  COUNTER_EVIDENCE: ['search_evidence', 'get_evidence', 'get_graph_neighbors', 'get_driver_decomposition'],
  CAUSAL_SELECTOR: ['get_evidence'],
  CONFIDENCE_JUDGE: ['get_evidence'],
}

/** Hand-ported from causa/src/tools/gateway.py::TOOL_REGISTRY (classification column only). */
export const TOOL_REGISTRY: ToolDefinition[] = [
  { toolName: 'get_kpi', allowedAgents: ['HYPOTHESIS', 'EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch a single-period KPI value.' },
  { toolName: 'compare_kpi', allowedAgents: ['EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Compare a KPI across two periods.' },
  { toolName: 'get_materiality', allowedAgents: ['EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Run the anomaly/materiality engine for a KPI+period.' },
  {
    toolName: 'get_driver_decomposition',
    allowedAgents: ['HYPOTHESIS', 'EVIDENCE', 'COUNTER_EVIDENCE'],
    classification: 'INTERNAL',
    description: 'Run the PVM driver decomposition engine.',
  },
  { toolName: 'get_concurrent_kpis', allowedAgents: ['HYPOTHESIS', 'EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch several KPIs’ concurrent movement.' },
  { toolName: 'search_evidence', allowedAgents: ['HYPOTHESIS', 'EVIDENCE', 'COUNTER_EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Governed hybrid retrieval over structured + review evidence.' },
  {
    toolName: 'get_evidence',
    allowedAgents: ['EVIDENCE', 'COUNTER_EVIDENCE', 'CAUSAL_SELECTOR', 'CONFIDENCE_JUDGE'],
    classification: 'PUBLIC_ANALYTICAL',
    description: 'Fetch one evidence object by id.',
  },
  { toolName: 'get_graph_neighbors', allowedAgents: ['EVIDENCE', 'COUNTER_EVIDENCE'], classification: 'PUBLIC_ANALYTICAL', description: 'Fetch neighbors of a node in the evidence graph.' },
]

interface PromptInjectionFile {
  note: string
  fixtures: { fixture_id: string; text: string }[]
}

export async function getPromptInjectionFixtures(): Promise<PromptInjectionFixture[]> {
  const r = await loadFixture<PromptInjectionFile>('prompt_injection_fixtures')
  return r.fixtures.map((f) => ({ fixtureId: f.fixture_id, text: f.text }))
}

const INJECTION_PATTERNS: { label: string; re: RegExp }[] = [
  { label: 'instruction override', re: /ignore (all )?(previous|prior) instructions?/i },
  { label: 'role hijack', re: /(act as|you are now|as the) (developer|orchestrator|admin)/i },
  { label: 'system prompt exfiltration', re: /(reveal|show).{0,20}(system prompt|api key)/i },
  { label: 'unauthorized data request', re: /(all|every) (customer|seller).{0,15}(emails?|records?)/i },
  { label: 'command injection', re: /execute this command|run sql/i },
  { label: 'evidence-boundary escape', re: /<\/?UNTRUSTED_EVIDENCE>/i },
  { label: 'unauthorized state transition', re: /transition (my )?investigation status|approve this action without/i },
]

/** Deterministic, client-side re-implementation of what src/agents/security.py
 * demonstrates: injection-shaped text is classified UNTRUSTED and never
 * reaches tool execution or investigation state, regardless of content. */
export function runPromptInjectionDemo(fixture: PromptInjectionFixture): PromptInjectionDemoResult {
  const detected = INJECTION_PATTERNS.filter((p) => p.re.test(fixture.text)).map((p) => p.label)
  return {
    fixtureId: fixture.fixtureId,
    sourceText: fixture.text,
    source: 'Customer Review',
    classification: 'UNTRUSTED_SOURCE_TEXT',
    detected: detected.length ? detected : ['pattern not matched by this demo’s local classifier'],
    action: 'BLOCKED',
    toolExecution: 'NONE',
    dataDisclosure: 'NONE',
  }
}

export function runRbacDemo(requesterRole: RequesterRole, requestedClassification: SecurityClassification): RBACDemoResult {
  const clearance = RBAC_CLEARANCE_FOR_ROLE[requesterRole]
  const allowed = CLEARANCE_RANK[clearance] >= CLEARANCE_RANK[requestedClassification]
  return {
    requesterRole,
    requestedClassification,
    requesterClearance: clearance,
    decision: allowed ? 'ALLOWED' : 'DENIED',
    reason: allowed
      ? `${requesterRole} clearance (${clearance}) covers ${requestedClassification}.`
      : `${requesterRole} clearance (${clearance}) is insufficient for ${requestedClassification} — request denied before any tool executes.`,
  }
}
