import { useQuery } from '@tanstack/react-query'
import { getConcurrentKpiMovements, getDriverDecomposition } from '@/api'
import { useAppState } from '@/state/AppStateContext'
import { CLEARANCE_RANK, RBAC_CLEARANCE_FOR_ROLE } from '@/api'

/** Whether the current requester's clearance covers the INTERNAL dimensions
 * (seller / seller_state) — governs drill-down visibility everywhere. */
export function useClearanceAllowsInternal() {
  const { requesterRole } = useAppState()
  return CLEARANCE_RANK[RBAC_CLEARANCE_FOR_ROLE[requesterRole]] >= CLEARANCE_RANK.INTERNAL
}

export function useDriverDecomposition() {
  const allowsInternal = useClearanceAllowsInternal()
  return useQuery({
    queryKey: ['driver-decomposition', allowsInternal],
    queryFn: () => getDriverDecomposition(allowsInternal),
  })
}

export function useConcurrentKpiMovements() {
  return useQuery({ queryKey: ['concurrent-kpis'], queryFn: getConcurrentKpiMovements })
}
