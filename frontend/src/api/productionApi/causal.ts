import type { CausalResult, EligibilityCheck, EligibilityReport } from '@/types/causal'
import { apiFetch } from './client'
import { getCurrentInvestigationId } from './investigations'

interface RawCheck { check_name: string; status: string; reason: string; evidence_ids: string[] }
interface RawEligibility { hypothesis_id: string; verdict: string; checks: RawCheck[] }
interface RawCausalResult {
  hypothesis_id: string; method: string; evidence_tier: string; status: string
  estimate: Record<string, number | string> | null; assumptions: string[]; diagnostics: unknown[]
  confounders: string[]; evidence_ids: string[]; limitations: string[]; causal_claim_allowed: boolean
  eligibility_report: RawEligibility
}

function mapEligibility(raw: RawEligibility): EligibilityReport {
  return {
    hypothesisId: raw.hypothesis_id, verdict: raw.verdict as EligibilityReport['verdict'],
    checks: raw.checks.map((c): EligibilityCheck => ({
      checkName: c.check_name, status: c.status as EligibilityCheck['status'], reason: c.reason, evidenceIds: c.evidence_ids,
    })),
  }
}

function mapResult(raw: RawCausalResult): CausalResult {
  return {
    hypothesisId: raw.hypothesis_id, method: raw.method as CausalResult['method'],
    evidenceTier: raw.evidence_tier as CausalResult['evidenceTier'], status: raw.status as CausalResult['status'],
    estimate: raw.estimate, assumptions: raw.assumptions, diagnostics: raw.diagnostics.map((d) => String(d)),
    confounders: raw.confounders, evidenceIds: raw.evidence_ids, limitations: raw.limitations,
    causalClaimAllowed: raw.causal_claim_allowed, eligibilityReport: mapEligibility(raw.eligibility_report),
  }
}

export async function getCausalResults(): Promise<CausalResult[]> {
  const id = await getCurrentInvestigationId('ANALYST')
  const r = await apiFetch<{ results: Array<RawCausalResult | { error: string; hypothesis_id: string }> }>(
    `/api/investigations/${id}/causal-analysis?requester_role=ANALYST`,
  )
  return r.results.filter((x): x is RawCausalResult => !('error' in x)).map(mapResult)
}

export async function getCausalResult(hypothesisId: string): Promise<CausalResult | undefined> {
  const all = await getCausalResults()
  return all.find((c) => c.hypothesisId === hypothesisId)
}

/** No backend equivalent -- src/causal has no "synthetic demonstration"
 * endpoint (that concept lives only in scripts/step6_causal_validation.py's
 * own report). Returns an explicitly-empty, labeled result rather than
 * fabricating one. */
export async function getSyntheticMethodDemonstrations() {
  return {} as Record<string, { evidence_tier: string; causal_claim_allowed: boolean; status: string; note: string }>
}

export async function getCausalHonestAbstentionNote(): Promise<string> {
  const results = await getCausalResults()
  if (results.length > 0) return ''
  return 'No Step 5 hypothesis for this investigation bridged into a structurally valid causal hypothesis ' +
    '(e.g. the investigation abstained before producing a usable hypothesis) -- this is reported honestly, ' +
    'never backfilled with a fabricated causal claim.'
}

export async function getCausalGraphSummary() {
  const r = await apiFetch<{ node_count: number; edge_count: number; nodes: Array<{ node_type?: string }> }>('/api/evidence/graph/full')
  return { n_nodes: r.node_count, n_edges: r.edge_count, node_types: [...new Set(r.nodes.map((n) => n.node_type).filter(Boolean))] as string[] }
}
