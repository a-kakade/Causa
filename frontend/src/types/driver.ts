/** Mirrors src/drivers/models.py — the Step 3D PVM engine. */

export interface PVMBreakdown {
  volumeEffect: number
  priceEffect: number
  mixEffect: number
  reconciled: boolean
  reconciliationError: number
}

export interface DriverContribution {
  driver: 'volume' | 'price' | 'mix'
  contributionValue: number
  contributionPctOfChange: number
  direction: 'positive' | 'negative'
  method: string
  /** Hardcoded false on the backend model — a decomposition is never a causal claim. */
  causalClaim: false
  evidenceId?: string
}

export interface SegmentContribution {
  dimension: string
  segment: string
  contributionValue: number
  contributionPctOfChange: number
  rank: number
  restricted?: boolean
  evidenceId?: string
}

export interface DriverDecompositionResult {
  kpiId: string
  periodCurrent: string
  periodPrevious: string
  pvm: PVMBreakdown
  driverContributions: DriverContribution[]
  topCategoryContributions: SegmentContribution[]
  topSellerStateContributions: SegmentContribution[]
  causalClaim: false
}
