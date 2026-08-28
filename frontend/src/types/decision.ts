/** Mirrors src/decision/models.py — Step 7 Decision/Action Engine. */

export interface DriverSignal {
  driver: string
  driverCategory: string
  kpiId: string
  period: string
  observedChangePct: number | null
  observedChangeAbsolute: number | null
  addressablePopulation: number | null
  addressablePopulationSource: string
  historicalEstimatedEffect: number | null
  historicalEffectSource: string
  driverConfidence: number
  causalClaimAllowed: boolean | null
  causalResultId: string | null
  source: 'MANUAL' | 'DRIVER_ENGINE' | 'CAUSAL_ENGINE'
}

export interface ExpectedImpact {
  metric: string
  estimatedEffect: number
  effectUnit: string
  addressablePopulation: number | null
  confidence: number
  calculatedImpact: number | null
  revenueImpact: number | null
  effectSource: string
  populationSource: string
  confidenceBasis: string
  isEstimable: boolean
}

export type ConstraintStatus = 'PASS' | 'WARNING' | 'BLOCKED'

export interface ConstraintCheck {
  constraint: string
  status: ConstraintStatus
  details: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH'
}

export interface MonitoringTarget {
  kpi: string
  direction: 'increase' | 'decrease'
  expectedEffect: number
  target: string
  window: string
  warningThreshold: number
  stopCondition: string
}

export interface ScoreBreakdown {
  confidenceFactors: Record<string, number>
  confidenceWeights: Record<string, number>
  confidenceScore: number
  controllabilityScore: number
  controllabilityBasis: string
  effortScore: number
  effortBasis: string
  priorityFormula: string
  priorityScore: number
}

export type RecommendationTier = 'TOP' | 'ALTERNATIVE' | 'CONDITIONAL' | 'BLOCKED'

/** Mirrors src/decision/models.py::ActionRecommendation */
export interface ActionRecommendation {
  recommendationId: string
  driver: string
  driverCategory: string
  controllableLever: string
  possibleAction: string
  expectedImpact: ExpectedImpact
  owner: string
  constraints: ConstraintCheck[]
  controllability: number
  effort: number
  priorityScore: number
  monitoringKpis: MonitoringTarget[]
  rationale: string
  assumptions: string[]
  scoreBreakdown: ScoreBreakdown
  tier: RecommendationTier
  rankingExplanation: string[]
  /** false unless the driver behind this recommendation is backed by a
   * real evidence/causal result — governs the "evidence-backed" badge. */
  actionJustifiedByEvidence: boolean
  generatedBy: string
  sourceDriverSignalId: string
}

export interface DecisionResult {
  requestId: string
  driverSignal: DriverSignal
  topRecommendation: ActionRecommendation | null
  alternatives: ActionRecommendation[]
  conditional: ActionRecommendation[]
  blocked: ActionRecommendation[]
  allCandidatesEvaluated: number
}
