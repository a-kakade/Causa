import { useQuery } from '@tanstack/react-query'
import { getKpiMovement, getKpiMovements, getKpiTrendSeries } from '@/api'

export function useKpiMovements() {
  return useQuery({ queryKey: ['kpi-movements'], queryFn: getKpiMovements })
}

export function useKpiMovement(kpiId: string) {
  return useQuery({ queryKey: ['kpi-movement', kpiId], queryFn: () => getKpiMovement(kpiId) })
}

export function useKpiTrend(kpiId: string) {
  return useQuery({ queryKey: ['kpi-trend', kpiId], queryFn: () => getKpiTrendSeries(kpiId) })
}
