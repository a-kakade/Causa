import type { ConfidenceLevel, LineageStep, SecurityClassification, SecurityStatus, TrustLevel } from './common'

/** T4/T5 exist in the enum but are never instantiated by the real backend
 * (Step 4/6 validation: "reserved, never populated"). Kept here so the UI's
 * tier ladder can render them as explicitly unreached rungs. */
export type EvidenceTier =
  | 'T1_DESCRIPTIVE'
  | 'T2_ARITHMETIC'
  | 'T3_STATISTICAL'
  | 'T4_CAUSAL'
  | 'T5_EXPERIMENTAL'

export type EvidenceType =
  | 'KPI_OBSERVATION'
  | 'KPI_MOVEMENT'
  | 'ANOMALY_SIGNAL'
  | 'DRIVER_CONTRIBUTION'
  | 'SEGMENT_CONTRIBUTION'
  | 'CONCURRENT_KPI'
  | 'STATISTICAL_RESULT'
  | 'CUSTOMER_REVIEW'

/** Mirrors EvidenceObject (causa/src/evidence/schema.py), strict/extra=forbid
 * on the backend — every field here is a real field the backend emits. */
export interface EvidenceObject {
  evidenceId: string
  evidenceType: EvidenceType
  evidenceTier: EvidenceTier
  claim: string
  value: { value: number | string | null; unit: string | null }
  time: { start: string; end: string }
  dimensions: Record<string, string | number>
  confidence: ConfidenceLevel
  source: { system: string; component: string; version: string }
  lineage: LineageStep[]
  freshness: {
    eventTime: string
    dataAvailabilityTime: string | null
    processingTime: string
    isHistorical: boolean
  }
  quality: {
    completeness: number | null
    freshness: number | null
    sourceReliability: number | null
    coverage: number | null
    historicalSufficiency: number | null
    retrievalQuality: number | null
  }
  security: {
    classification: SecurityClassification
    trustLevel: TrustLevel
    securityStatus: SecurityStatus
    piiDetected?: boolean
    piiTypes?: string[]
    redactionStatus?: string
  }
  relationships: { type: string; targetId: string }[]
  metadata: Record<string, unknown>
  createdAt: string
  /** Only present on CUSTOMER_REVIEW evidence — the raw review text.
   * Always render this as untrusted source data, never as an instruction. */
  content?: string
  retrieval?: { rank: number; score: number; method: string }
}

export interface ContradictionCheck {
  segment: string
  previousLowScoreRate: number
  currentLowScoreRate: number
  nPrevious: number
  nCurrent: number
  zScore: number
  contradicts: boolean
}

export interface EvidenceGraphNode {
  id: string
  label: string
  type: 'INVESTIGATION' | 'KPI' | 'MOVEMENT' | 'DRIVER' | 'SEGMENT' | 'EVIDENCE' | 'CONFIDENCE' | 'ACTION' | 'CAUSAL_ANALYSIS' | 'ASSUMPTION'
  value?: number
  /** Free-form tier label — carries either an EvidenceTier or a CausalTier
   * string depending on the node, display purposes only. */
  tier?: string
}

export type EvidenceEdgeType =
  | 'HAS_MOVEMENT'
  | 'EXPLAINED_BY'
  | 'SUPPORTED_BY'
  | 'CONTRADICTS'
  | 'CONTEXTUALIZED_BY'
  | 'DERIVED_FROM'
  | 'HAS_CONFIDENCE'
  | 'RECOMMENDS'
  | 'TESTED_BY'
  | 'ASSOCIATED_WITH'

export interface EvidenceGraphEdge {
  source: string
  target: string
  type: EvidenceEdgeType
  /** Never true unless the backend's causal_claim_allowed is true for the
   * underlying analysis — the graph must not render an edge as causal
   * otherwise (spec: "Do NOT label an edge causal unless causal_claim_allowed"). */
  causalClaimAllowed: boolean
}
