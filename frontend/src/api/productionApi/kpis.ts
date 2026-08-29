import type { KPIMovement } from '@/types/kpi'
import { apiFetch, getApiPeriod } from './client'

interface RawComparisonResult {
  kpi_id: string
  current_value: number | null
  previous_value: number | null
  absolute_change: number | null
  percentage_change: number | null
}

interface OverviewResponse {
  period: string
  previous_period: string
  kpi_movements: RawComparisonResult[]
  headline_anomaly: { materiality: { verdict: string } }
}

const LOWER_IS_BETTER = new Set(['avg_delivery_days'])

function mapMovement(raw: RawComparisonResult, period: string, previousPeriod: string, materiality: string | null): KPIMovement {
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
  const { period, previousPeriod } = getApiPeriod()
  const r = await apiFetch<OverviewResponse>(
    `/api/overview?period=${period}&previous_period=${previousPeriod}`,
  )
  const verdict = r.headline_anomaly?.materiality?.verdict ?? null
  return r.kpi_movements.map((m) => mapMovement(m, r.period, r.previous_period, verdict))
}

export async function getKpiMovement(kpiId: string): Promise<KPIMovement | undefined> {
  const all = await getKpiMovements()
  return all.find((k) => k.kpiId === kpiId)
}
