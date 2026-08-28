import type { CausalResult, EligibilityCheck, EligibilityReport } from '@/types/causal'
import { loadFixture } from './loadFixture'

interface RawCheck {
  check_name: string
  status: string
  reason: string
  evidence_ids: string[]
}

interface RawEligibility {
  hypothesis_id: string
  verdict: string
  checks: RawCheck[]
}

interface RawCausalResult {
  hypothesis_id: string
  method: string
  evidence_tier: string
  status: string
  estimate: Record<string, number | string> | null
  assumptions: string[]
  diagnostics: unknown[]
  confounders: string[]
  evidence_ids: string[]
  limitations: string[]
  causal_claim_allowed: boolean
  eligibility_report: RawEligibility
}

interface Step6Report {
  results_by_hypothesis: Record<string, RawCausalResult>
  synthetic_method_demonstrations: Record<
    string,
    { evidence_tier: string; causal_claim_allowed: boolean; status: string; note: string }
  >
  evidence_graph_summary: { n_nodes: number; n_edges: number; node_types: string[] }
  honest_abstention_note: string
}

function mapEligibility(raw: RawEligibility): EligibilityReport {
  return {
    hypothesisId: raw.hypothesis_id,
    verdict: raw.verdict as EligibilityReport['verdict'],
    checks: raw.checks.map(
      (c): EligibilityCheck => ({
        checkName: c.check_name,
        status: c.status as EligibilityCheck['status'],
        reason: c.reason,
        evidenceIds: c.evidence_ids,
      }),
    ),
  }
}

function mapResult(raw: RawCausalResult): CausalResult {
  return {
    hypothesisId: raw.hypothesis_id,
    method: raw.method as CausalResult['method'],
    evidenceTier: raw.evidence_tier as CausalResult['evidenceTier'],
    status: raw.status as CausalResult['status'],
    estimate: raw.estimate,
    assumptions: raw.assumptions,
    diagnostics: raw.diagnostics.map((d) => String(d)),
    confounders: raw.confounders,
    evidenceIds: raw.evidence_ids,
    limitations: raw.limitations,
    causalClaimAllowed: raw.causal_claim_allowed,
    eligibilityReport: mapEligibility(raw.eligibility_report),
  }
}

let cached: Step6Report | null = null
async function report(): Promise<Step6Report> {
  if (!cached) cached = await loadFixture<Step6Report>('step6_validation')
  return cached
}

/** The 4 real hypotheses tested against the Nov 2017 Olist scenario. In
 * hypothesis_id order: order-volume, category-growth, delivery/review,
 * geographic concentration. */
export async function getCausalResults(): Promise<CausalResult[]> {
  const r = await report()
  return Object.values(r.results_by_hypothesis).map(mapResult)
}

export async function getCausalResult(hypothesisId: string): Promise<CausalResult | undefined> {
  const all = await getCausalResults()
  return all.find((c) => c.hypothesisId === hypothesisId)
}

/** Synthetic constructed demonstrations proving the machinery CAN reach
 * T3_QUASI_EXPERIMENTAL — explicitly labeled "not an Olist finding" by the
 * backend. Rendered only inside a clearly-marked "methodology capability"
 * panel, never mixed into the real Nov 2017 conclusions. */
export async function getSyntheticMethodDemonstrations() {
  const r = await report()
  return r.synthetic_method_demonstrations
}

export async function getCausalHonestAbstentionNote(): Promise<string> {
  const r = await report()
  return r.honest_abstention_note
}

export async function getCausalGraphSummary() {
  const r = await report()
  return r.evidence_graph_summary
}
