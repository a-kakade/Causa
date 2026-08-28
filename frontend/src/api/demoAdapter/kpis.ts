import type { KPIMovement } from '@/types/kpi'
import { DEMO_PERIOD_CURRENT, DEMO_PERIOD_PREVIOUS } from './kpiRegistry'
import { loadFixture } from './loadFixture'

interface Step4Report {
  kpi_movement_checks: Record<string, { computed_pct_change: number }>
  revenue_absolute_change_check: { computed: number }
  materiality_check: { verdict: string }
  full_structured_evidence: RawEvidence[]
}

interface RawEvidence {
  evidence_id: string
  evidence_type: string
  claim: string
  value: { value: number | null }
  dimensions: Record<string, unknown>
}

// KPIs where a smaller value is the favorable direction.
const LOWER_IS_BETTER = new Set(['avg_delivery_days'])

function currentAndPrevious(claim: string): { previous: number; current: number } | null {
  // "revenue moved from 664219.43 (...) to 1010271.3699999999 (...), a change of ..."
  const m = claim.match(/moved from ([\d.]+) .*? to ([\d.]+)/)
  if (!m) return null
  return { previous: Number(m[1]), current: Number(m[2]) }
}

export async function getKpiMovements(): Promise<KPIMovement[]> {
  const step4 = await loadFixture<Step4Report>('step4_validation')
  const checks = step4.kpi_movement_checks

  const kpiMoveEvidence = step4.full_structured_evidence.filter((e) => e.evidence_type === 'KPI_MOVEMENT')

  const out: KPIMovement[] = []
  for (const [kpiId, check] of Object.entries(checks)) {
    const evidence = kpiMoveEvidence.find((e) => e.claim.startsWith(`${kpiId} moved`))
    const parsed = evidence ? currentAndPrevious(evidence.claim) : null
    const pct = check.computed_pct_change
    const direction = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
    const favorable = LOWER_IS_BETTER.has(kpiId) ? direction === 'down' : direction === 'up'

    out.push({
      kpiId,
      period: DEMO_PERIOD_CURRENT,
      previousPeriod: DEMO_PERIOD_PREVIOUS,
      currentValue: parsed?.current ?? Number.NaN,
      previousValue: parsed?.previous ?? Number.NaN,
      absoluteChange:
        kpiId === 'revenue' ? step4.revenue_absolute_change_check.computed : (parsed ? parsed.current - parsed.previous : Number.NaN),
      percentageChange: pct,
      direction,
      favorable,
      materiality: kpiId === 'revenue' ? (step4.materiality_check.verdict as KPIMovement['materiality']) : null,
      evidenceId: evidence?.evidence_id,
    })
  }
  return out
}

export async function getKpiMovement(kpiId: string): Promise<KPIMovement | undefined> {
  const all = await getKpiMovements()
  return all.find((k) => k.kpiId === kpiId)
}
