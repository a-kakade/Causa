import type { ContradictionCheck, EvidenceObject } from '@/types/evidence'
import { loadFixture } from './loadFixture'

interface RawEvidence {
  evidence_id: string
  evidence_type: string
  evidence_tier: string
  claim: string
  // The Step 4 report's retrieval-sample buckets (sample_retrieval_results)
  // carry a deliberately reduced shape — no value/time/dimensions/quality/
  // freshness/confidence/created_at — vs. the full EvidenceObject schema
  // (full_structured_evidence, sample_review_evidence). Every optional field
  // below reflects that real difference, not a data error.
  value?: { value: number | string | null; unit: string | null }
  time?: { start: string; end: string }
  dimensions?: Record<string, unknown>
  confidence?: string
  source: { system: string; component: string; version: string }
  lineage: { layer: string; reference: string }[]
  freshness?: { event_time: string; data_availability_time: string | null; processing_time: string; is_historical: boolean }
  quality?: Record<string, number | null>
  security: {
    classification: string
    trust_level: string
    security_status: string
    pii_detected?: boolean
    pii_types?: string[]
    redaction_status?: string
  }
  relationships?: { type: string; target_id: string }[]
  metadata: Record<string, unknown>
  created_at?: string
  content?: string
  retrieval?: { rank: number; score: number; method: string }
}

function mapEvidence(raw: RawEvidence): EvidenceObject {
  return {
    evidenceId: raw.evidence_id,
    evidenceType: raw.evidence_type as EvidenceObject['evidenceType'],
    evidenceTier: raw.evidence_tier as EvidenceObject['evidenceTier'],
    claim: raw.claim,
    value: raw.value ?? { value: null, unit: null },
    time: raw.time ?? { start: '', end: '' },
    dimensions: (raw.dimensions ?? {}) as EvidenceObject['dimensions'],
    confidence: (raw.confidence ?? 'UNKNOWN') as EvidenceObject['confidence'],
    source: raw.source,
    lineage: raw.lineage,
    freshness: {
      eventTime: raw.freshness?.event_time ?? '',
      dataAvailabilityTime: raw.freshness?.data_availability_time ?? null,
      processingTime: raw.freshness?.processing_time ?? '',
      isHistorical: raw.freshness?.is_historical ?? true,
    },
    quality: {
      completeness: raw.quality?.completeness ?? null,
      freshness: raw.quality?.freshness ?? null,
      sourceReliability: raw.quality?.source_reliability ?? null,
      coverage: raw.quality?.coverage ?? null,
      historicalSufficiency: raw.quality?.historical_sufficiency ?? null,
      retrievalQuality: raw.quality?.retrieval_quality ?? null,
    },
    security: {
      classification: raw.security.classification as EvidenceObject['security']['classification'],
      trustLevel: raw.security.trust_level as EvidenceObject['security']['trustLevel'],
      securityStatus: raw.security.security_status as EvidenceObject['security']['securityStatus'],
      piiDetected: raw.security.pii_detected,
      piiTypes: raw.security.pii_types,
      redactionStatus: raw.security.redaction_status,
    },
    relationships: (raw.relationships ?? []).map((r) => ({ type: r.type, targetId: r.target_id })),
    metadata: raw.metadata ?? {},
    createdAt: raw.created_at ?? '',
    content: raw.content,
    retrieval: raw.retrieval,
  }
}

interface Step4Report {
  full_structured_evidence: RawEvidence[]
  sample_review_evidence: RawEvidence[]
  sample_retrieval_results: Record<string, RawEvidence[]>
  contradiction_checks: Record<
    string,
    { previous_low_score_rate: number; current_low_score_rate: number; n_previous: number; n_current: number; z_score: number; contradicts: boolean }
  >
  graph_summary: { n_nodes: number; n_edges: number; node_types: string[]; relationship_types: string[] }
  review_evidence_count: number
  review_language_distribution: Record<string, number>
  review_pii_detected_count: number
  structured_evidence_count: number
  structured_evidence_by_type: Record<string, number>
}

let cached: Step4Report | null = null
async function report(): Promise<Step4Report> {
  if (!cached) cached = await loadFixture<Step4Report>('step4_validation')
  return cached
}

export async function getStructuredEvidence(): Promise<EvidenceObject[]> {
  const r = await report()
  return r.full_structured_evidence.map(mapEvidence)
}

export async function getEvidenceById(id: string): Promise<EvidenceObject | undefined> {
  const all = await getStructuredEvidence()
  const found = all.find((e) => e.evidenceId === id)
  if (found) return found
  const reviews = await getReviewEvidenceSamples()
  return reviews.find((e) => e.evidenceId === id)
}

export async function getReviewEvidenceSamples(): Promise<EvidenceObject[]> {
  const r = await report()
  const seen = new Set<string>()
  const all = [...r.sample_review_evidence, ...Object.values(r.sample_retrieval_results).flat()]
  const out: EvidenceObject[] = []
  for (const raw of all) {
    if (seen.has(raw.evidence_id)) continue
    seen.add(raw.evidence_id)
    out.push(mapEvidence(raw))
  }
  return out
}

export async function getRetrievalBuckets(): Promise<Record<string, EvidenceObject[]>> {
  const r = await report()
  const out: Record<string, EvidenceObject[]> = {}
  for (const [bucket, items] of Object.entries(r.sample_retrieval_results)) {
    out[bucket] = items.map(mapEvidence)
  }
  return out
}

export async function getContradictionChecks(): Promise<ContradictionCheck[]> {
  const r = await report()
  return Object.entries(r.contradiction_checks).map(([segment, c]) => ({
    segment,
    previousLowScoreRate: c.previous_low_score_rate,
    currentLowScoreRate: c.current_low_score_rate,
    nPrevious: c.n_previous,
    nCurrent: c.n_current,
    zScore: c.z_score,
    contradicts: c.contradicts,
  }))
}

export async function getEvidenceGraphSummary() {
  const r = await report()
  return r.graph_summary
}

export async function getReviewCorpusStats() {
  const r = await report()
  return {
    reviewEvidenceCount: r.review_evidence_count,
    languageDistribution: r.review_language_distribution,
    piiDetectedCount: r.review_pii_detected_count,
    structuredEvidenceCount: r.structured_evidence_count,
    structuredEvidenceByType: r.structured_evidence_by_type,
  }
}
