import { apiFetch } from './client'

export interface MonthlyPoint {
  period: string
  orders: number | null
  revenue: number | null
  avgDeliveryDays: number | null
  avgReviewScore: number | null
  aov: number | null
  freightRevenue: number | null
  onTimeDeliveryRate: number | null
  reviewVolume: number | null
  repeatPurchaseRate: number | null
}

const MONTHS = [
  '2017-01', '2017-02', '2017-03', '2017-04', '2017-05', '2017-06',
  '2017-07', '2017-08', '2017-09', '2017-10', '2017-11', '2017-12',
]
const KPI_IDS: Array<{ id: string; field: keyof MonthlyPoint }> = [
  { id: 'revenue', field: 'revenue' }, { id: 'orders', field: 'orders' }, { id: 'aov', field: 'aov' },
  { id: 'avg_delivery_days', field: 'avgDeliveryDays' }, { id: 'avg_review_score', field: 'avgReviewScore' },
  { id: 'freight_revenue', field: 'freightRevenue' }, { id: 'on_time_delivery_rate', field: 'onTimeDeliveryRate' },
  { id: 'review_volume', field: 'reviewVolume' }, { id: 'repeat_purchase_rate', field: 'repeatPurchaseRate' },
]

interface TimeseriesResponse {
  kpi_id: string
  points: { period: string; value: number | null }[]
}

let cached: Promise<MonthlyPoint[]> | null = null

export async function getMonthlyKpiTimeseries(): Promise<MonthlyPoint[]> {
  if (!cached) {
    cached = Promise.all(
      KPI_IDS.map((k) => apiFetch<TimeseriesResponse>(`/api/kpis/${k.id}/timeseries?months=${MONTHS.join(',')}`)),
    ).then((responses) => {
      const byMonthField: Record<string, Partial<MonthlyPoint>> = {}
      responses.forEach((resp, i) => {
        const field = KPI_IDS[i].field
        for (const p of resp.points) {
          byMonthField[p.period] = { ...byMonthField[p.period], period: p.period, [field]: p.value }
        }
      })
      return MONTHS.map((m) => ({
        period: m, orders: null, revenue: null, avgDeliveryDays: null, avgReviewScore: null, aov: null,
        freightRevenue: null, onTimeDeliveryRate: null, reviewVolume: null, repeatPurchaseRate: null,
        ...byMonthField[m],
      }))
    })
  }
  return cached
}

const FIELD_BY_KPI: Record<string, keyof MonthlyPoint> = {
  revenue: 'revenue', orders: 'orders', aov: 'aov',
  avg_delivery_days: 'avgDeliveryDays', avg_review_score: 'avgReviewScore',
  freight_revenue: 'freightRevenue', on_time_delivery_rate: 'onTimeDeliveryRate',
  review_volume: 'reviewVolume', repeat_purchase_rate: 'repeatPurchaseRate',
}

export async function getKpiTrendSeries(kpiId: string): Promise<{ period: string; value: number | null }[]> {
  const field = FIELD_BY_KPI[kpiId]
  const series = await getMonthlyKpiTimeseries()
  if (!field) return []
  return series.map((p) => ({ period: p.period, value: p[field] as number | null }))
}
