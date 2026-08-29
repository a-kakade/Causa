import type { ActionRecommendation, ConstraintCheck, DecisionResult, DriverSignal, MonitoringTarget, ScoreBreakdown } from '@/types/decision'
import { apiFetch } from './client'
import { getCurrentInvestigationId } from './investigations'

export type DecisionKey = 'delivery_delay' | 'aov_decline'

interface RawRec {
  recommendation_id: string; driver: string; driver_category: string; controllable_lever: string; possible_action: string
  expected_impact: Record<string, unknown>
  owner: string
  constraints: { constraint: string; status: string; details: string; severity: string }[]
  controllability: number; effort: number; priority_score: number
  monitoring_kpis: Record<string, unknown>[]
  rationale: string; assumptions: string[]
  score_breakdown: Record<string, unknown>
  tier: string; ranking_explanation: string[]; action_justified_by_evidence: boolean
  generated_by: string; source_driver_signal_id: string
}
interface RawDriverSignal {
  driver: string; driver_category: string; kpi_id: string; period: string
  observed_change_pct: number | null; observed_change_absolute: number | null
  addressable_population: number | null; addressable_population_source: string
  historical_estimated_effect: number | null; historical_effect_source: string
  driver_confidence: number | null; causal_claim_allowed: boolean | null; causal_result_id: string | null; source: string
}
interface RawDecisionResult {
  investigation_id?: string
  request_id?: string
  driver_signal?: RawDriverSignal
  top_recommendation: RawRec | null
  alternatives: RawRec[]
  conditional: RawRec[]
  blocked: RawRec[]
  all_candidates_evaluated: number
  pipeline_trace: string[]
}

function mapRec(raw: RawRec): ActionRecommendation {
  const ei = raw.expected_impact as Record<string, unknown>
  const sb = raw.score_breakdown as Record<string, unknown>
  return {
    recommendationId: raw.recommendation_id, driver: raw.driver, driverCategory: raw.driver_category,
    controllableLever: raw.controllable_lever, possibleAction: raw.possible_action,
    expectedImpact: {
      metric: String(ei.metric ?? ''), estimatedEffect: (ei.estimated_effect as number) ?? null,
      effectUnit: String(ei.effect_unit ?? ''), addressablePopulation: (ei.addressable_population as number) ?? null,
      confidence: (ei.confidence as number) ?? null, calculatedImpact: (ei.calculated_impact as number) ?? null,
      revenueImpact: (ei.revenue_impact as number) ?? null, effectSource: String(ei.effect_source ?? ''),
      populationSource: String(ei.population_source ?? ''), confidenceBasis: String(ei.confidence_basis ?? ''),
      isEstimable: Boolean(ei.is_estimable),
    },
    owner: raw.owner,
    constraints: raw.constraints.map((c): ConstraintCheck => ({
      constraint: c.constraint, status: c.status as ConstraintCheck['status'], details: c.details,
      severity: c.severity as ConstraintCheck['severity'],
    })),
    controllability: raw.controllability, effort: raw.effort, priorityScore: raw.priority_score,
    monitoringKpis: raw.monitoring_kpis.map((m): MonitoringTarget => ({
      kpi: String(m.kpi), direction: m.direction as MonitoringTarget['direction'],
      expectedEffect: (m.expected_effect as number | null) ?? Number.NaN,
      target: String(m.target ?? ''), window: String(m.window ?? ''),
      warningThreshold: (m.warning_threshold as number | null) ?? Number.NaN,
      stopCondition: String(m.stop_condition ?? ''),
    })),
    rationale: raw.rationale, assumptions: raw.assumptions,
    scoreBreakdown: {
      confidenceFactors: (sb.confidence_factors as Record<string, number>) ?? {},
      confidenceWeights: (sb.confidence_weights as Record<string, number>) ?? {},
      confidenceScore: (sb.confidence_score as number) ?? 0, controllabilityScore: (sb.controllability_score as number) ?? 0,
      controllabilityBasis: String(sb.controllability_basis ?? ''), effortScore: (sb.effort_score as number) ?? 0,
      effortBasis: String(sb.effort_basis ?? ''), priorityFormula: String(sb.priority_formula ?? ''),
      priorityScore: (sb.priority_score as number) ?? 0,
    } satisfies ScoreBreakdown,
    tier: raw.tier as ActionRecommendation['tier'], rankingExplanation: raw.ranking_explanation,
    actionJustifiedByEvidence: raw.action_justified_by_evidence, generatedBy: raw.generated_by,
    sourceDriverSignalId: raw.source_driver_signal_id,
  }
}

function mapResult(raw: RawDecisionResult): DecisionResult {
  const ds = raw.driver_signal
  const driverSignal: DriverSignal = ds
    ? {
        driver: ds.driver, driverCategory: ds.driver_category, kpiId: ds.kpi_id, period: ds.period,
        observedChangePct: ds.observed_change_pct, observedChangeAbsolute: ds.observed_change_absolute,
        addressablePopulation: ds.addressable_population, addressablePopulationSource: ds.addressable_population_source,
        historicalEstimatedEffect: ds.historical_estimated_effect, historicalEffectSource: ds.historical_effect_source,
        driverConfidence: ds.driver_confidence ?? Number.NaN, causalClaimAllowed: ds.causal_claim_allowed,
        causalResultId: ds.causal_result_id, source: ds.source as DriverSignal['source'],
      }
    : { driver: '', driverCategory: '', kpiId: '', period: '', observedChangePct: null, observedChangeAbsolute: null,
        addressablePopulation: null, addressablePopulationSource: 'UNKNOWN', historicalEstimatedEffect: null,
        historicalEffectSource: 'UNKNOWN', driverConfidence: Number.NaN, causalClaimAllowed: null, causalResultId: null, source: 'MANUAL' }
  return {
    requestId: raw.request_id ?? raw.investigation_id ?? '', driverSignal,
    topRecommendation: raw.top_recommendation ? mapRec(raw.top_recommendation) : null,
    alternatives: raw.alternatives.map(mapRec), conditional: raw.conditional.map(mapRec), blocked: raw.blocked.map(mapRec),
    allCandidatesEvaluated: raw.all_candidates_evaluated,
  }
}

/** The demo build's DecisionKey ('delivery_delay'|'aov_decline') was a fixed
 * demo-script enum; the real API is investigation-scoped instead. Both keys
 * resolve to the current (Analyst-role) investigation's own recommendations
 * -- documented in docs/FRONTEND_BACKEND_INTEGRATION.md as an intentional
 * shape simplification pending a richer investigation picker in the UI. */
export async function getDecisionResult(_key: DecisionKey): Promise<DecisionResult> {
  const id = await getCurrentInvestigationId('ANALYST')
  const raw = await apiFetch<RawDecisionResult>(`/api/investigations/${id}/recommendations?requester_role=ANALYST`)
  return mapResult(raw)
}

export async function getAllDecisionResults(): Promise<Record<DecisionKey, DecisionResult>> {
  const result = await getDecisionResult('delivery_delay')
  return { delivery_delay: result, aov_decline: result }
}

export async function getDecisionNarrative(key: DecisionKey): Promise<string> {
  const r = await getDecisionResult(key)
  return r.topRecommendation?.rationale ?? 'No recommendation narrative available for this investigation.'
}
