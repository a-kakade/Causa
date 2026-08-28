import { useQuery } from '@tanstack/react-query'
import { getTelemetryView } from '@/api'

export function useTelemetryView(role: 'ANALYST' | 'EXECUTIVE') {
  return useQuery({ queryKey: ['telemetry', role], queryFn: () => getTelemetryView(role) })
}
