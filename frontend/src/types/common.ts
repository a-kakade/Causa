/**
 * Shared enums mirrored 1:1 from the CAUSA backend (causa/src/evidence/models.py,
 * causa/src/agents/models.py). Field names and value strings match the real
 * Pydantic enums exactly so demo-adapter fixtures (real backend JSON output)
 * can be typed without translation.
 */

export type SecurityClassification = 'PUBLIC_ANALYTICAL' | 'INTERNAL' | 'RESTRICTED'

export type TrustLevel = 'TRUSTED_SYSTEM' | 'UNTRUSTED_DATA'

export type SecurityStatus = 'SAFE' | 'FLAGGED' | 'BLOCKED'

export type RequesterRole = 'EXECUTIVE' | 'ANALYST' | 'INTERNAL'

export type AgentRole =
  | 'ORCHESTRATOR'
  | 'HYPOTHESIS'
  | 'EVIDENCE'
  | 'COUNTER_EVIDENCE'
  | 'CAUSAL_SELECTOR'
  | 'CONFIDENCE_JUDGE'

export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'ABSTAIN' | 'NEEDS_CLARIFICATION' | 'UNKNOWN'

export const CLEARANCE_RANK: Record<SecurityClassification, number> = {
  PUBLIC_ANALYTICAL: 0,
  INTERNAL: 1,
  RESTRICTED: 2,
}

export interface LineageStep {
  layer: string
  reference: string
}

/** Distinguishes a value the frontend computed/labeled for presentation from
 * one lifted verbatim off a backend fixture. Every view-model field that
 * carries a real number is expected to be `sourced`. */
export type Sourced<T> = T
