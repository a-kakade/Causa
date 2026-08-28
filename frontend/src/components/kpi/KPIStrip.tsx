import { KPICard } from './KPICard'
import { Skeleton } from '@/components/common/LoadingState'
import { useKpiMovements } from '@/hooks/useKpis'
import { kpiDef } from '@/api/demoAdapter/kpiRegistry'

const HEADLINE_KPI_IDS = ['revenue', 'orders', 'aov', 'avg_delivery_days', 'avg_review_score']

export function KPIStrip() {
  const { data: movements, isLoading } = useKpiMovements()

  if (isLoading) {
    return (
      <div className="grid grid-cols-5 gap-3">
        {HEADLINE_KPI_IDS.map((id) => (
          <Skeleton key={id} className="h-[104px]" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-5 gap-3">
      {HEADLINE_KPI_IDS.map((kpiId) => {
        const def = kpiDef(kpiId)
        const movement = movements?.find((m) => m.kpiId === kpiId)
        if (!def || !movement) return null
        return <KPICard key={kpiId} def={def} movement={movement} />
      })}
    </div>
  )
}
