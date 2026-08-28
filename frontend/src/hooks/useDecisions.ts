import { useQuery } from '@tanstack/react-query'
import { getAllDecisionResults } from '@/api'

export function useDecisions() {
  return useQuery({ queryKey: ['decisions'], queryFn: getAllDecisionResults })
}
