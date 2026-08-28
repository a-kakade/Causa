import type { ActionRecommendation, ConstraintCheck, DecisionResult, DriverSignal, MonitoringTarget, ScoreBreakdown } from '@/types/decision'
import { loadFixture } from './loadFixture'

interface RawRec {
  recommendation_id: string
  driver: string
  driver_category: string
  controllable_lever: string
  possible_action: string
  expected_impact: {
    metric: string
    estimated_effect: number
    effect_unit: string
    addressable_population: number | null
    confidence: number
    calculated_impact: number | null
    revenue_impact: number | null
    effect_source: string
    population_source: string
    confidence_basis: string
    is_estimable: boolean
  }
  owner: string
  constraints: { constraint: string; status: string; details: string; severity: string }[]
  controllability: number
  effort: number
  priority_score: number
  monitoring_kpis: {
    kpi: string
    direction: string
    expected_effect: number
    target: string
    window: string
    warning_threshold: number
    stop_condition: string
  }[]
  rationale: string
  assumptions: string[]
  score_breakdown: {
    confidence_factors: Record<string, number>
    confidence_weights: Record<string, number>
    confidence_score: number
    controllability_score: number
    controllability_basis: string
    effort_score: number
    effort_basis: string
    priority_formula: string
    priority_score: number
  }
  tier: string
  ranking_explanation: string[]
  action_justified_by_evidence: boolean
  generated_by: string
  source_driver_signal_id: string
}

interface RawDriverSignal {
  driver: string
  driver_category: string
  kpi_id: string
  period: string
  observed_change_pct: number | null
  observed_change_absolute: number | null
  addressable_population: number | null
  addressable_population_source: string
  historical_estimated_effect: number | null
  historical_effect_source: string
  driver_confidence: number
  causal_claim_allowed: boolean | null
  causal_result_id: string | null
  source: string
}

interface RawDecisionResult {
  request_id: string
  driver_signal: RawDriverSignal
  top_recommendation: RawRec | null
  alternatives: RawRec[]
  conditional: RawRec[]
  blocked: RawRec[]
  all_candidates_evaluated: number
  pipeline_trace: string[]
}

interface Step7Report {
  results: Record<string, RawDecisionResult>
  narratives: Record<string, string>
}

function mapRec(raw: RawRec): ActionRecommendation {
  return {
    recommendationId: raw.recommendation_id,
    driver: raw.driver,
    driverCategory: raw.driver_category,
    controllableLever: raw.controllable_lever,
    possibleAction: raw.possible_action,
    expectedImpact: {
      metric: raw.expected_impact.metric,
      estimatedEffect: raw.expected_impact.estimated_effect,
      effectUnit: raw.expected_impact.effect_unit,
      addressablePopulation: raw.expected_impact.addressable_population,
      confidence: raw.expected_impact.confidence,
      calculatedImpact: raw.expected_impact.calculated_impact,
      revenueImpact: raw.expected_impact.revenue_impact,
      effectSource: raw.expected_impact.effect_source,
      populationSource: raw.expected_impact.population_source,
      confidenceBasis: raw.expected_impact.confidence_basis,
      isEstimable: raw.expected_impact.is_estimable,
    },
    owner: raw.owner,
    constraints: raw.constraints.map(
      (c): ConstraintCheck => ({
        constraint: c.constraint,
        status: c.status as ConstraintCheck['status'],
        details: c.details,
        severity: c.severity as ConstraintCheck['severity'],
      }),
    ),
    controllability: raw.controllability,
    effort: raw.effort,
    priorityScore: raw.priority_score,
    monitoringKpis: raw.monitoring_kpis.map(
      (m): MonitoringTarget => ({
        kpi: m.kpi,
        direction: m.direction as MonitoringTarget['direction'],
        expectedEffect: m.expected_effect,
        target: m.target,
        window: m.window,
        warningThreshold: m.warning_threshold,
        stopCondition: m.stop_condition,
      }),
    ),
    rationale: raw.rationale,
    assumptions: raw.assumptions,
    scoreBreakdown: {
      confidenceFactors: raw.score_breakdown.confidence_factors,
      confidenceWeights: raw.score_breakdown.confidence_weights,
      confidenceScore: raw.score_breakdown.confidence_score,
      controllabilityScore: raw.score_breakdown.controllability_score,
      controllabilityBasis: raw.score_breakdown.controllability_basis,
      effortScore: raw.score_breakdown.effort_score,
      effortBasis: raw.score_breakdown.effort_basis,
      priorityFormula: raw.score_breakdown.priority_formula,
      priorityScore: raw.score_breakdown.priority_score,
    } satisfies ScoreBreakdown,
    tier: raw.tier as ActionRecommendation['tier'],
    rankingExplanation: raw.ranking_explanation,
    actionJustifiedByEvidence: raw.action_justified_by_evidence,
    generatedBy: raw.generated_by,
    sourceDriverSignalId: raw.source_driver_signal_id,
  }
}

function mapDriverSignal(raw: RawDriverSignal): DriverSignal {
  return {
    driver: raw.driver,
    driverCategory: raw.driver_category,
    kpiId: raw.kpi_id,
    period: raw.period,
    observedChangePct: raw.observed_change_pct,
    observedChangeAbsolute: raw.observed_change_absolute,
    addressablePopulation: raw.addressable_population,
    addressablePopulationSource: raw.addressable_population_source,
    historicalEstimatedEffect: raw.historical_estimated_effect,
    historicalEffectSource: raw.historical_effect_source,
    driverConfidence: raw.driver_confidence,
    causalClaimAllowed: raw.causal_claim_allowed,
    causalResultId: raw.causal_result_id,
    source: raw.source as DriverSignal['source'],
  }
}

let cached: Step7Report | null = null
async function report(): Promise<Step7Report> {
  if (!cached) cached = await loadFixture<Step7Report>('step7_validation')
  return cached
}

export type DecisionKey = 'delivery_delay' | 'aov_decline'

export async function getDecisionResult(key: DecisionKey): Promise<DecisionResult> {
  const r = await report()
  const raw = r.results[key]
  return {
    requestId: raw.request_id,
    driverSignal: mapDriverSignal(raw.driver_signal),
    topRecommendation: raw.top_recommendation ? mapRec(raw.top_recommendation) : null,
    alternatives: raw.alternatives.map(mapRec),
    conditional: raw.conditional.map(mapRec),
    blocked: raw.blocked.map(mapRec),
    allCandidatesEvaluated: raw.all_candidates_evaluated,
  }
}

export async function getAllDecisionResults(): Promise<Record<DecisionKey, DecisionResult>> {
  const [dd, aov] = await Promise.all([getDecisionResult('delivery_delay'), getDecisionResult('aov_decline')])
  return { delivery_delay: dd, aov_decline: aov }
}

export async function getDecisionNarrative(key: DecisionKey): Promise<string> {
  const r = await report()
  return r.narratives[key]
}
