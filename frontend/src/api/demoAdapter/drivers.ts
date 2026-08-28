import type { DriverContribution, DriverDecompositionResult, PVMBreakdown, SegmentContribution } from '@/types/driver'
import type { KPIMovement } from '@/types/kpi'
import { loadFixture } from './loadFixture'

interface RawDriver {
  driver: string
  contribution_value: number
  contribution_pct_of_change: number
  direction: 'positive' | 'negative'
  method: string
}

interface RawSegment {
  segment_value: string
  contribution: number
  rank: number
}

interface Step3DReport {
  full_result: {
    kpi_id: string
    period_current: string
    period_previous: string
    total_change: number
    drivers: RawDriver[]
    reconciliation: { sum_of_contributions: number; actual_change: number; error: number; reconciled: boolean }
    concurrent_kpis: Record<string, { previous_value: number; current_value: number; absolute_change: number; percentage_change: number; warnings: string[] }>
  }
  contribution_tree_sample: {
    segments: Record<string, RawSegment[]>
  }
  pvm_checksum: number
}

/** Dimensions the KPI semantic layer classifies INTERNAL — governed by RBAC,
 * never surfaced to a requester whose clearance is below INTERNAL. */
export const RESTRICTED_DIMENSIONS = new Set(['seller', 'seller_state'])

let cached: Step3DReport | null = null
async function report(): Promise<Step3DReport> {
  if (!cached) cached = await loadFixture<Step3DReport>('step3d_validation')
  return cached
}

export async function getPVM(): Promise<PVMBreakdown> {
  const r = await report()
  const byName = Object.fromEntries(r.full_result.drivers.map((d) => [d.driver, d]))
  return {
    volumeEffect: byName.volume?.contribution_value ?? 0,
    priceEffect: byName.price?.contribution_value ?? 0,
    mixEffect: byName.mix?.contribution_value ?? 0,
    reconciled: r.full_result.reconciliation.reconciled,
    reconciliationError: r.full_result.reconciliation.error,
  }
}

export async function getDriverContributions(): Promise<DriverContribution[]> {
  const r = await report()
  return r.full_result.drivers.map((d) => ({
    driver: d.driver as DriverContribution['driver'],
    contributionValue: d.contribution_value,
    contributionPctOfChange: d.contribution_pct_of_change,
    direction: d.direction,
    method: d.method,
    causalClaim: false,
  }))
}

export async function getSegmentContributions(
  dimension: 'product_category' | 'customer_state' | 'seller' | 'seller_state',
  clearanceAllows: boolean,
): Promise<SegmentContribution[]> {
  const r = await report()
  const rows = r.contribution_tree_sample.segments[dimension] ?? []
  const restricted = RESTRICTED_DIMENSIONS.has(dimension) && !clearanceAllows
  return rows.map((row) => ({
    dimension,
    segment: restricted ? '••••••••' : row.segment_value,
    contributionValue: restricted ? Number.NaN : row.contribution,
    contributionPctOfChange: Number.NaN,
    rank: row.rank,
    restricted,
  }))
}

export async function getConcurrentKpiMovements(): Promise<KPIMovement[]> {
  const r = await report()
  const LOWER_IS_BETTER = new Set(['avg_delivery_days'])
  return Object.entries(r.full_result.concurrent_kpis).map(([kpiId, v]) => {
    const direction = v.percentage_change > 0 ? 'up' : v.percentage_change < 0 ? 'down' : 'flat'
    return {
      kpiId,
      period: r.full_result.period_current,
      previousPeriod: r.full_result.period_previous,
      currentValue: v.current_value,
      previousValue: v.previous_value,
      absoluteChange: v.absolute_change,
      percentageChange: v.percentage_change,
      direction,
      favorable: LOWER_IS_BETTER.has(kpiId) ? direction === 'down' : direction === 'up',
      materiality: null,
    }
  })
}

export async function getDriverDecomposition(clearanceAllows: boolean): Promise<DriverDecompositionResult> {
  const r = await report()
  const [pvm, driverContributions, categories, sellerStates] = await Promise.all([
    getPVM(),
    getDriverContributions(),
    getSegmentContributions('product_category', clearanceAllows),
    getSegmentContributions('seller_state', clearanceAllows),
  ])
  return {
    kpiId: r.full_result.kpi_id,
    periodCurrent: r.full_result.period_current,
    periodPrevious: r.full_result.period_previous,
    pvm,
    driverContributions,
    topCategoryContributions: categories,
    topSellerStateContributions: sellerStates,
    causalClaim: false,
  }
}
