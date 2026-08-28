import { useQuery } from '@tanstack/react-query'
import { getCausalResults, getSyntheticMethodDemonstrations } from '@/api'

export function useCausalResults() {
  return useQuery({ queryKey: ['causal-results'], queryFn: getCausalResults })
}

export function useSyntheticMethodDemonstrations() {
  return useQuery({ queryKey: ['causal-synthetic-demos'], queryFn: getSyntheticMethodDemonstrations })
}
