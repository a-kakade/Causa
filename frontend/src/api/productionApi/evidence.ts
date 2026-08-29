import type { ContradictionCheck, EvidenceObject } from '@/types/evidence'
import { apiFetch } from './client'

interface RawEvidence {
  evidence_id: string
  evidence_type: string
  evidence_tier: string
  claim: string
  value?: { value: number | string | null; unit: string | null }
  time?: { start: string; end: string }
  dimensions?: Record<string, unknown>
  confidence?: string
  source: { system: string; component: string; version: string }
  lineage: { layer: string; reference: string }[]
  freshness?: { event_time: string; data_availability_time: string | null; processing_time: string; is_historical: boolean }
  quality?: Record<string, number | null>
  security: { classification: string; trust_level: string; security_status: string; pii_detected?: boolean; pii_types?: string[]; redaction_status?: string }
  relationships?: { relationship_type: string; target_evidence_id: string }[]
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
      eventTime: raw.freshness?.event_time ?? '', dataAvailabilityTime: raw.freshness?.data_availability_time ?? null,
      processingTime: raw.freshness?.processing_time ?? '', isHistorical: raw.freshness?.is_historical ?? true,
    },
    quality: {
      completeness: raw.quality?.completeness ?? null, freshness: raw.quality?.freshness ?? null,
      sourceReliability: raw.quality?.source_reliability ?? null, coverage: raw.quality?.coverage ?? null,
      historicalSufficiency: raw.quality?.historical_sufficiency ?? null, retrievalQuality: raw.quality?.retrieval_quality ?? null,
    },
    security: {
      classification: raw.security.classification as EvidenceObject['security']['classification'],
      trustLevel: raw.security.trust_level as EvidenceObject['security']['trustLevel'],
      securityStatus: raw.security.security_status as EvidenceObject['security']['securityStatus'],
      piiDetected: raw.security.pii_detected, piiTypes: raw.security.pii_types, redactionStatus: raw.security.redaction_status,
    },
    relationships: (raw.relationships ?? []).map((r) => ({ type: r.relationship_type, targetId: r.target_evidence_id })),
    metadata: raw.metadata ?? {},
    createdAt: raw.created_at ?? '',
    content: raw.content,
    retrieval: raw.retrieval,
  }
}

// No module-level cache here (unlike demoAdapter's fixture-backed version) --
// the result is RBAC-clearance-dependent (the same URL returns different
// data per requester_role), so caching must be react-query's job (keyed per
// query, invalidated on role change by AppStateContext), never a raw
// promise cache that would silently return a stale role's data.
export async function getStructuredEvidence(): Promise<EvidenceObject[]> {
  const r = await apiFetch<{ evidence: RawEvidence[] }>('/api/evidence')
  return r.evidence.map(mapEvidence)
}

export async function getEvidenceById(id: string): Promise<EvidenceObject | undefined> {
  try {
    const raw = await apiFetch<RawEvidence>(`/api/evidence/${id}`)
    return mapEvidence(raw)
  } catch {
    return undefined
  }
}

export async function getReviewEvidenceSamples(): Promise<EvidenceObject[]> {
  const r = await apiFetch<{ results: RawEvidence[] }>('/api/evidence/search/reviews?question=Which+reviews+describe+delivery+delays%3F&month=2017-11&top_k=15')
  return r.results.map(mapEvidence)
}

export async function getRetrievalBuckets(): Promise<Record<string, EvidenceObject[]>> {
  const [delivery, lowScore] = await Promise.all([
    apiFetch<{ results: RawEvidence[] }>('/api/evidence/search/reviews?question=delivery+delays&month=2017-11&top_k=10'),
    apiFetch<{ results: RawEvidence[] }>('/api/evidence/search/reviews?question=lowest+scored+reviews&month=2017-11&top_k=10'),
  ])
  return { delivery_related: delivery.results.map(mapEvidence), low_score: lowScore.results.map(mapEvidence) }
}

export async function getContradictionChecks(): Promise<ContradictionCheck[]> {
  // The API surfaces real CONTRADICTS-typed graph edges rather than the raw
  // z-score fixture shape the demo build's fixture happens to carry --
  // callers wanting the graph edges directly should use getEvidenceGraph().
  const r = await apiFetch<{ contradiction_edges: Array<Record<string, unknown>> }>('/api/evidence/contradictions/checks')
  return r.contradiction_edges.map((e, i) => ({
    segment: String(e.source ?? `edge_${i}`), previousLowScoreRate: Number.NaN, currentLowScoreRate: Number.NaN,
    nPrevious: 0, nCurrent: 0, zScore: Number.NaN, contradicts: true,
  }))
}

export async function getEvidenceGraphSummary() {
  const r = await apiFetch<{ node_count: number; edge_count: number; nodes: Array<{ node_type?: string }> }>('/api/evidence/graph/full')
  return {
    n_nodes: r.node_count, n_edges: r.edge_count,
    node_types: [...new Set(r.nodes.map((n) => n.node_type).filter(Boolean))] as string[],
    relationship_types: [],
  }
}

export async function getReviewCorpusStats() {
  const all = await getStructuredEvidence()
  const reviews = all.filter((e) => e.evidenceType === 'CUSTOMER_REVIEW')
  const byType: Record<string, number> = {}
  for (const e of all) byType[e.evidenceType] = (byType[e.evidenceType] ?? 0) + 1
  return {
    reviewEvidenceCount: reviews.length, languageDistribution: {} as Record<string, number>,
    piiDetectedCount: reviews.filter((r) => r.security.piiDetected).length,
    structuredEvidenceCount: all.length, structuredEvidenceByType: byType,
  }
}
