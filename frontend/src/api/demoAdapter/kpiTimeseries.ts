/**
 * Real monthly KPI time series from causa/reports/kpi_timeseries_monthly.csv
 * (Step 1 EDA output over the canonical Olist data — the same source the
 * KPI engine's history/baseline logic draws on). Sliced to the KPI
 * contract's governed default window (2017-01..2018-08, config/kpis.yaml
 * shared_valid_time_window) so bootstrap months with near-zero volume don't
 * distort the trend.
 */

export interface MonthlyPoint {
  period: string // "2017-01"
  orders: number | null
  revenue: number | null
  avgDeliveryDays: number | null
  avgReviewScore: number | null
  aov: number | null
}

const WINDOW_START = '2017-01'
const WINDOW_END = '2018-08'

let cached: Promise<MonthlyPoint[]> | null = null

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split('\n')
  const headers = lines[0].split(',')
  return lines.slice(1).map((line) => {
    const cells = line.split(',')
    const row: Record<string, string> = {}
    headers.forEach((h, i) => {
      row[h] = cells[i] ?? ''
    })
    return row
  })
}

function num(v: string): number | null {
  if (v === '' || v === undefined || v.toLowerCase() === 'inf' || v.toLowerCase() === '-inf') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export async function getMonthlyKpiTimeseries(): Promise<MonthlyPoint[]> {
  if (!cached) {
    cached = fetch('/fixtures/kpi_timeseries_monthly.csv')
      .then((r) => r.text())
      .then((text) =>
        parseCsv(text)
          .map(
            (row): MonthlyPoint => ({
              period: row.order_purchase_timestamp.slice(0, 7),
              orders: num(row.orders),
              revenue: num(row.revenue),
              avgDeliveryDays: num(row.avg_delivery_days),
              avgReviewScore: num(row.avg_review_score),
              aov: num(row.aov),
            }),
          )
          .filter((p) => p.period >= WINDOW_START && p.period <= WINDOW_END),
      )
  }
  return cached
}

const FIELD_BY_KPI: Record<string, keyof MonthlyPoint> = {
  revenue: 'revenue',
  orders: 'orders',
  aov: 'aov',
  avg_delivery_days: 'avgDeliveryDays',
  avg_review_score: 'avgReviewScore',
}

export async function getKpiTrendSeries(kpiId: string): Promise<{ period: string; value: number | null }[]> {
  const field = FIELD_BY_KPI[kpiId]
  const series = await getMonthlyKpiTimeseries()
  if (!field) return []
  return series.map((p) => ({ period: p.period, value: p[field] as number | null }))
}
