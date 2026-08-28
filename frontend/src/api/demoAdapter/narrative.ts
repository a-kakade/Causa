import type { EvidencePackageItem, KPIStory, NarrativeClaim, NumericClaim, Persona, StorySection } from '@/types/narrative'
import { loadFixture } from './loadFixture'

interface RawNumericClaim {
  raw_text: string
  normalized_value: number
  unit: string
  matched_evidence_id: string | null
  status: string
  rejection_reason: string | null
}

interface RawClaim {
  text: string
  claim_type: string
  evidence_ids: string[]
  confidence: string
  numeric_claims: RawNumericClaim[]
  validation_status: string
  rejection_reason: string | null
}

interface RawSection {
  title: string
  statements: RawClaim[]
}

interface RawStory {
  persona: string
  headline: string
  sections: RawSection[]
  verification: { status: string; claims_checked: number; claims_rejected: number; rejected_claims: string[] }
  generated_by: string
  evidence_package_id: string
  evidence_package_version: string
  evidence_package_hash: string
}

interface RawEvidencePackageItem {
  evidence_id: string
  metric: string
  value: number
  unit: string
  direction: string
  period: string
  source_system: string
  analytical_method: string
  confidence: string
  claim_type: string
  evidence_type: string
  evidence_tier: string
}

interface Step8Report {
  evidence_package: { package_id: string; kpi_id: string; period: string; items: RawEvidencePackageItem[]; version: string; content_hash: string }
  stories: Record<string, RawStory>
}

function mapNumericClaim(raw: RawNumericClaim): NumericClaim {
  return {
    rawText: raw.raw_text,
    normalizedValue: raw.normalized_value,
    unit: raw.unit,
    matchedEvidenceId: raw.matched_evidence_id,
    status: raw.status as NumericClaim['status'],
    rejectionReason: raw.rejection_reason,
  }
}

function mapClaim(raw: RawClaim): NarrativeClaim {
  return {
    text: raw.text,
    claimType: raw.claim_type as NarrativeClaim['claimType'],
    evidenceIds: raw.evidence_ids,
    confidence: raw.confidence,
    numericClaims: raw.numeric_claims.map(mapNumericClaim),
    validationStatus: raw.validation_status as NarrativeClaim['validationStatus'],
    rejectionReason: raw.rejection_reason,
  }
}

function mapStory(raw: RawStory): KPIStory {
  return {
    persona: raw.persona as Persona,
    headline: raw.headline,
    sections: raw.sections.map((s): StorySection => ({ title: s.title, statements: s.statements.map(mapClaim) })),
    verification: {
      status: raw.verification.status as KPIStory['verification']['status'],
      claimsChecked: raw.verification.claims_checked,
      claimsRejected: raw.verification.claims_rejected,
      rejectedClaims: raw.verification.rejected_claims,
    },
    generatedBy: raw.generated_by,
    evidencePackageId: raw.evidence_package_id,
    evidencePackageVersion: raw.evidence_package_version,
    evidencePackageHash: raw.evidence_package_hash,
  }
}

let cached: Step8Report | null = null
async function report(): Promise<Step8Report> {
  if (!cached) cached = await loadFixture<Step8Report>('step8_validation')
  return cached
}

export async function getStory(persona: Persona): Promise<KPIStory> {
  const r = await report()
  return mapStory(r.stories[persona])
}

export async function getAllStories(): Promise<Record<Persona, KPIStory>> {
  const r = await report()
  const out = {} as Record<Persona, KPIStory>
  for (const [k, v] of Object.entries(r.stories)) out[k as Persona] = mapStory(v)
  return out
}

export async function getEvidencePackageItems(): Promise<EvidencePackageItem[]> {
  const r = await report()
  return r.evidence_package.items.map(
    (i): EvidencePackageItem => ({
      evidenceId: i.evidence_id,
      metric: i.metric,
      value: i.value,
      unit: i.unit,
      direction: i.direction as EvidencePackageItem['direction'],
      period: i.period,
      sourceSystem: i.source_system,
      analyticalMethod: i.analytical_method,
      confidence: i.confidence,
      claimType: i.claim_type as EvidencePackageItem['claimType'],
      evidenceType: i.evidence_type,
      evidenceTier: i.evidence_tier,
    }),
  )
}

export async function getEvidencePackageMeta() {
  const r = await report()
  return {
    packageId: r.evidence_package.package_id,
    kpiId: r.evidence_package.kpi_id,
    period: r.evidence_package.period,
    version: r.evidence_package.version,
    contentHash: r.evidence_package.content_hash,
  }
}
