import type { DriverContribution, DriverDecompositionResult, PVMBreakdown, SegmentContribution } from '@/types/driver'
import type { KPIMovement } from '@/types/kpi'
import { apiFetch } from './client'
import { DEMO_PERIOD_CURRENT, DEMO_PERIOD_PREVIOUS } from './kpiRegistry'

/** Segment-level access control is now enforced SERVER-SIDE
 * (drivers.engine.decompose's own requester_clearance check) -- this
 * constant is kept only as a UI hint for which dimensions to warn about
 * before the request round-trips; the server is the actual authority. */
export const RESTRICTED_DIMENSIONS = new Set(['seller', 'seller_state'])

interface RawDriverDecomposition {
  kpi_id: string
  period_current: string
  period_previous: string
  total_change: { absolute: number; percentage: number | null }
  drivers: { driver: string; contribution_value: number; contribution_pct_of_change: number | null; direction: string; method: string }[]
  segment_contributions: Record<string, { segment_value: string; absolute_change: number; rank: number | null }[]>
  concurrent_kpis: Record<string, { previous_value: number | null; current_value: number | null; absolute_change: number | null; percentage_change: number | null; warnings: string[] }>
  reconciliation: { sum_of_contributions: number; actual_change: number; error: number; reconciled: boolean }
}

async function fetchDecomposition(segments?: string): Promise<RawDriverDecomposition> {
  const q = segments ? `&segments=${segments}` : ''
  return apiFetch<RawDriverDecomposition>(
    `/api/kpis/revenue/drivers?period=${DEMO_PERIOD_CURRENT}&previous_period=${DEMO_PERIOD_PREVIOUS}${q}`,
  )
}

export async function getPVM(): Promise<PVMBreakdown> {
  const r = await fetchDecomposition('')
  const byName = Object.fromEntries(r.drivers.map((d) => [d.driver, d]))
  return {
    volumeEffect: byName.volume?.contribution_value ?? 0,
    priceEffect: byName.price?.contribution_value ?? 0,
    mixEffect: byName.mix?.contribution_value ?? 0,
    reconciled: r.reconciliation.reconciled,
    reconciliationError: r.reconciliation.error,
  }
}

export async function getDriverContributions(): Promise<DriverContribution[]> {
  const r = await fetchDecomposition('')
  return r.drivers.map((d) => ({
    driver: d.driver as DriverContribution['driver'],
    contributionValue: d.contribution_value,
    contributionPctOfChange: d.contribution_pct_of_change ?? Number.NaN,
    direction: d.direction as DriverContribution['direction'],
    method: d.method,
    causalClaim: false,
  }))
}

export async function getSegmentContributions(
  dimension: 'product_category' | 'customer_state' | 'seller' | 'seller_state',
  clearanceAllows: boolean,
): Promise<SegmentContribution[]> {
  if (RESTRICTED_DIMENSIONS.has(dimension) && !clearanceAllows) {
    // Avoid a round-trip that the server would 403 anyway; render the same
    // redacted placeholder shape the demo build uses.
    return []
  }
  const r = await fetchDecomposition(dimension)
  const rows = r.segment_contributions[dimension] ?? []
  return rows.map((row) => ({
    dimension,
    segment: row.segment_value,
    contributionValue: row.absolute_change,
    contributionPctOfChange: Number.NaN,
    rank: row.rank ?? 0,
    restricted: false,
  }))
}

export async function getConcurrentKpiMovements(): Promise<KPIMovement[]> {
  const r = await fetchDecomposition('')
  const LOWER_IS_BETTER = new Set(['avg_delivery_days'])
  return Object.entries(r.concurrent_kpis).map(([kpiId, v]) => {
    const pct = v.percentage_change ?? 0
    const direction = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
    return {
      kpiId, period: r.period_current, previousPeriod: r.period_previous,
      currentValue: v.current_value ?? Number.NaN, previousValue: v.previous_value ?? Number.NaN,
      absoluteChange: v.absolute_change ?? Number.NaN, percentageChange: pct, direction,
      favorable: LOWER_IS_BETTER.has(kpiId) ? direction === 'down' : direction === 'up',
      materiality: null,
    }
  })
}

export async function getDriverDecomposition(clearanceAllows: boolean): Promise<DriverDecompositionResult> {
  const r = await fetchDecomposition(clearanceAllows ? 'product_category,seller_state' : 'product_category')
  const byName = Object.fromEntries(r.drivers.map((d) => [d.driver, d]))
  const categories: SegmentContribution[] = (r.segment_contributions.product_category ?? []).map((row) => ({
    dimension: 'product_category', segment: row.segment_value, contributionValue: row.absolute_change,
    contributionPctOfChange: Number.NaN, rank: row.rank ?? 0, restricted: false,
  }))
  const sellerStates: SegmentContribution[] = clearanceAllows
    ? (r.segment_contributions.seller_state ?? []).map((row) => ({
        dimension: 'seller_state', segment: row.segment_value, contributionValue: row.absolute_change,
        contributionPctOfChange: Number.NaN, rank: row.rank ?? 0, restricted: false,
      }))
    : []
  return {
    kpiId: r.kpi_id, periodCurrent: r.period_current, periodPrevious: r.period_previous,
    pvm: {
      volumeEffect: byName.volume?.contribution_value ?? 0, priceEffect: byName.price?.contribution_value ?? 0,
      mixEffect: byName.mix?.contribution_value ?? 0, reconciled: r.reconciliation.reconciled,
      reconciliationError: r.reconciliation.error,
    },
    driverContributions: r.drivers.map((d) => ({
      driver: d.driver as DriverContribution['driver'], contributionValue: d.contribution_value,
      contributionPctOfChange: d.contribution_pct_of_change ?? Number.NaN, direction: d.direction as DriverContribution['direction'],
      method: d.method, causalClaim: false,
    })),
    topCategoryContributions: categories,
    topSellerStateContributions: sellerStates,
    causalClaim: false,
  }
}
