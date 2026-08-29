import type { KPIMovement } from '@/types/kpi'
import { getDemoPeriod } from './client'
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

async function getCanonicalMovements(): Promise<KPIMovement[]> {
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

// --- per-period movements (real backend snapshots, see the fixture's own
// generation note below) -----------------------------------------------

/** demo_kpi_movements_by_period.json is a real GET /api/overview response
 * per single month of 2017 (period vs the immediately preceding month),
 * captured once from the actual running FastAPI backend -- not fabricated,
 * not hand-authored, just a wider snapshot than the single Oct->Nov 2017
 * canonical scenario the rest of the demo adapter is built on. Lets Demo
 * mode's KPI list / materiality verdicts actually vary with the Header's
 * period selector instead of freezing on one month regardless of what's
 * picked. Only single-month periods are covered (no multi-month ranges,
 * and no Jan 2017 -- its Dec-2016 baseline predates the dataset's governed
 * window, which the real backend itself reports as null/insufficient). */
interface RawComparisonResult {
  kpi_id: string
  current_value: number | null
  previous_value: number | null
  absolute_change: number | null
  percentage_change: number | null
}

interface PeriodSnapshot {
  period: string
  previous_period: string
  kpi_movements: RawComparisonResult[]
  materiality_verdict: string | null
}

let periodFixtureCache: Promise<Record<string, PeriodSnapshot>> | null = null
function periodFixture(): Promise<Record<string, PeriodSnapshot>> {
  if (!periodFixtureCache) periodFixtureCache = loadFixture('demo_kpi_movements_by_period')
  return periodFixtureCache
}

function mapSnapshotMovement(raw: RawComparisonResult, period: string, previousPeriod: string, materiality: string | null): KPIMovement {
  const pct = raw.percentage_change ?? 0
  const direction = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
  const favorable = LOWER_IS_BETTER.has(raw.kpi_id) ? direction === 'down' : direction === 'up'
  return {
    kpiId: raw.kpi_id,
    period,
    previousPeriod,
    currentValue: raw.current_value ?? Number.NaN,
    previousValue: raw.previous_value ?? Number.NaN,
    absoluteChange: raw.absolute_change ?? Number.NaN,
    percentageChange: pct,
    direction,
    favorable,
    materiality: raw.kpi_id === 'revenue' ? (materiality as KPIMovement['materiality']) : null,
    evidenceId: undefined,
  }
}

export async function getKpiMovements(): Promise<KPIMovement[]> {
  const { period } = getDemoPeriod()
  if (period === DEMO_PERIOD_CURRENT) return getCanonicalMovements()

  const snapshots = await periodFixture()
  const snap = snapshots[period]
  if (!snap) return getCanonicalMovements()
  return snap.kpi_movements.map((m) => mapSnapshotMovement(m, snap.period, snap.previous_period, snap.materiality_verdict))
}

export async function getKpiMovement(kpiId: string): Promise<KPIMovement | undefined> {
  const all = await getKpiMovements()
  return all.find((k) => k.kpiId === kpiId)
}
