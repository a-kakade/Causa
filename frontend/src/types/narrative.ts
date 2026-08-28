/** Mirrors src/story/models.py — Step 8 persona-aware narrative engine. */

export type Persona = 'EXECUTIVE' | 'FINANCE' | 'OPERATIONS' | 'MARKETING'

export type ClaimType = 'FACT' | 'ANALYTICAL_FINDING' | 'ASSOCIATION' | 'HYPOTHESIS' | 'UNKNOWN'

export interface NumericClaim {
  rawText: string
  normalizedValue: number
  unit: string
  matchedEvidenceId: string | null
  status: 'APPROVED' | 'REJECTED'
  rejectionReason: string | null
}

export interface NarrativeClaim {
  text: string
  claimType: ClaimType
  evidenceIds: string[]
  confidence: string
  numericClaims: NumericClaim[]
  validationStatus: 'APPROVED' | 'REJECTED'
  rejectionReason: string | null
}

export interface StorySection {
  title: string
  statements: NarrativeClaim[]
}

export interface VerificationResult {
  status: 'APPROVED' | 'REJECTED'
  claimsChecked: number
  claimsRejected: number
  rejectedClaims: string[]
}

/** Mirrors src/story/models.py::KPIStory */
export interface KPIStory {
  persona: Persona
  headline: string
  sections: StorySection[]
  verification: VerificationResult
  generatedBy: string
  evidencePackageId: string
  evidencePackageVersion: string
  evidencePackageHash: string
}

export interface EvidencePackageItem {
  evidenceId: string
  metric: string
  value: number
  unit: string
  direction: 'increase' | 'decrease' | 'flat'
  period: string
  sourceSystem: string
  analyticalMethod: string
  confidence: string
  claimType: ClaimType
  evidenceType: string
  evidenceTier: string
}
