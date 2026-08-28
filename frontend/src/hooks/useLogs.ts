import { useQuery } from '@tanstack/react-query'
import { getAllLogs } from '@/api'

export function useAllLogs() {
  return useQuery({ queryKey: ['logs'], queryFn: getAllLogs })
}
