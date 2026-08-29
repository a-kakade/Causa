import type { EvidencePackageItem, KPIStory, NarrativeClaim, NumericClaim, Persona, StorySection } from '@/types/narrative'
import { apiFetch } from './client'
import { getCurrentInvestigationId } from './investigations'

interface RawNumericClaim { raw_text: string; normalized_value: number; unit: string; matched_evidence_id: string | null; status: string; rejection_reason: string | null }
interface RawClaim { text: string; claim_type: string; evidence_ids: string[]; confidence: unknown; numeric_claims: RawNumericClaim[]; validation_status: string; rejection_reason: string | null }
interface RawSection { title: string; statements: RawClaim[] }
interface RawStory {
  persona: string; headline: string | null; sections: RawSection[]
  verification?: { status: string; claims_checked: number; claims_rejected: number; rejected_claims: unknown[] }
  verification_status?: string
  generated_by?: string; evidence_package_id?: string; evidence_package_version?: string; evidence_package_hash?: string
  reason?: string
}

function mapNumericClaim(raw: RawNumericClaim): NumericClaim {
  return { rawText: raw.raw_text, normalizedValue: raw.normalized_value, unit: raw.unit, matchedEvidenceId: raw.matched_evidence_id,
           status: raw.status as NumericClaim['status'], rejectionReason: raw.rejection_reason }
}
function mapClaim(raw: RawClaim): NarrativeClaim {
  return {
    text: raw.text, claimType: raw.claim_type as NarrativeClaim['claimType'], evidenceIds: raw.evidence_ids,
    confidence: String(raw.confidence ?? ''), numericClaims: raw.numeric_claims.map(mapNumericClaim),
    validationStatus: raw.validation_status as NarrativeClaim['validationStatus'], rejectionReason: raw.rejection_reason,
  }
}
function mapStory(raw: RawStory): KPIStory {
  return {
    persona: raw.persona as Persona, headline: raw.headline ?? '',
    sections: (raw.sections ?? []).map((s): StorySection => ({ title: s.title, statements: s.statements.map(mapClaim) })),
    verification: {
      status: (raw.verification?.status ?? raw.verification_status ?? 'PENDING') as KPIStory['verification']['status'],
      claimsChecked: raw.verification?.claims_checked ?? 0, claimsRejected: raw.verification?.claims_rejected ?? 0,
      rejectedClaims: (raw.verification?.rejected_claims as string[]) ?? [],
    },
    generatedBy: raw.generated_by ?? 'NOT_GENERATED',
    evidencePackageId: raw.evidence_package_id ?? '', evidencePackageVersion: raw.evidence_package_version ?? '',
    evidencePackageHash: raw.evidence_package_hash ?? '',
  }
}

export async function getStory(persona: Persona): Promise<KPIStory> {
  const id = await getCurrentInvestigationId('ANALYST')
  const raw = await apiFetch<RawStory>(`/api/investigations/${id}/story?persona=${persona}&requester_role=ANALYST`)
  return mapStory(raw)
}

export async function getAllStories(): Promise<Record<Persona, KPIStory>> {
  const personas: Persona[] = ['EXECUTIVE', 'FINANCE', 'OPERATIONS', 'MARKETING'] as Persona[]
  const stories = await Promise.all(personas.map((p) => getStory(p)))
  const out = {} as Record<Persona, KPIStory>
  personas.forEach((p, i) => { out[p] = stories[i] })
  return out
}

export async function getEvidencePackageItems(): Promise<EvidencePackageItem[]> {
  // The story evidence package is investigation-internal (built fresh per
  // GET /story call from the investigation's own evidence_ids); the API
  // does not separately expose it as a standalone resource today, so this
  // returns an empty list rather than fabricating package contents.
  return []
}

export async function getEvidencePackageMeta() {
  const id = await getCurrentInvestigationId('ANALYST')
  return { packageId: `pkg_${id}`, kpiId: 'revenue', period: '', version: '1.0', contentHash: '' }
}
