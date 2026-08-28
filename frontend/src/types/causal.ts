/** Mirrors src/causal/models.py — Step 6 causal eligibility / method selection engine. */

export type CausalTier = 'T1_DESCRIPTIVE' | 'T2_ARITHMETIC' | 'T3_QUASI_EXPERIMENTAL' | 'T4_EXPERIMENTAL'

export type CausalMethod =
  | 'DESCRIPTIVE_ASSOCIATION'
  | 'PVM'
  | 'DIFFERENCE_IN_DIFFERENCES'
  | 'INTERRUPTED_TIME_SERIES'
  | 'CAUSAL_IMPACT'
  | 'EXPERIMENTAL_RESULT'
  | 'NONE'

export type CausalStatus =
  | 'CAUSAL_SUPPORTED'
  | 'CAUSAL_INSUFFICIENT'
  | 'CAUSAL_REJECTED'
  | 'DESCRIPTIVE_ONLY'
  | 'ARITHMETIC_ONLY'

export type EligibilityVerdict = 'ELIGIBLE' | 'PARTIALLY_ELIGIBLE' | 'INELIGIBLE' | 'CAUSAL_INELIGIBLE'

export interface EligibilityCheck {
  checkName: string
  status: 'PASS' | 'HARD_FAIL' | 'SOFT_FAIL' | 'NOT_APPLICABLE'
  reason: string
  evidenceIds: string[]
}

export interface EligibilityReport {
  hypothesisId: string
  verdict: EligibilityVerdict
  checks: EligibilityCheck[]
}

export interface CausalHypothesis {
  hypothesisId: string
  treatment: string
  outcome: string
  proposedMechanism: string
  proposedMethod?: CausalMethod
}

/** Mirrors src/causal/models.py::CausalResult */
export interface CausalResult {
  hypothesisId: string
  method: CausalMethod
  evidenceTier: CausalTier
  status: CausalStatus
  estimate: Record<string, number | string> | null
  assumptions: string[]
  diagnostics: string[]
  confounders: string[]
  evidenceIds: string[]
  limitations: string[]
  causalClaimAllowed: boolean
  eligibilityReport: EligibilityReport
}
