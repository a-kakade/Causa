import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import { askInvestigationQuestion } from '@/api'
import { createInvestigation, getInvestigation } from '@/api'
import { useAppState } from '@/state/AppStateContext'
import type { RequesterRole } from '@/types/common'

/** Maps the app's 3-way RBAC role onto the 2 real investigation runs the
 * backend actually produced (analyst_investigation / executive_investigation)
 * — INTERNAL reuses the analyst run (it is the higher-clearance superset). */
function runFor(role: RequesterRole): 'ANALYST' | 'EXECUTIVE' {
  return role === 'EXECUTIVE' ? 'EXECUTIVE' : 'ANALYST'
}

/** Looks up (creating if needed) the investigation for the given KPI under
 * the current period/role -- keyed by (role, kpiId, period) so switching
 * KPIs never shows a stale cached result for a different one. */
export function useCurrentInvestigation(kpiId = 'revenue') {
  const { requesterRole, endPeriod, previousEndPeriod } = useAppState()
  const role = runFor(requesterRole)
  return useQuery({
    queryKey: ['investigation', role, kpiId, endPeriod, previousEndPeriod],
    queryFn: () => getInvestigation(role, kpiId, endPeriod, previousEndPeriod),
  })
}

export function useInvestigationByRole(role: 'ANALYST' | 'EXECUTIVE') {
  return useQuery({ queryKey: ['investigation', role], queryFn: () => getInvestigation(role) })
}

/** Explicitly triggers a fresh, real investigation run for a given KPI/
 * period (used by the "Investigate" button so it never silently reuses a
 * stale cached result). */
export function useCreateInvestigation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ role, kpiId, periodCurrent, periodPrevious, mode }: {
      role: 'ANALYST' | 'EXECUTIVE'; kpiId: string; periodCurrent: string; periodPrevious: string
      mode?: 'auto' | 'live' | 'fresh'
    }) => createInvestigation(role, kpiId, periodCurrent, periodPrevious, mode),
    onSuccess: (state, { role, kpiId, periodCurrent, periodPrevious }) => {
      queryClient.setQueryData(['investigation', role, kpiId, periodCurrent, periodPrevious], state)
      void queryClient.invalidateQueries({ queryKey: ['investigation'] })
    },
  })
}

/** "Ask your own question" -- runs a fresh, real investigation resolved
 * server-side from free text (see api.productionApi.investigations
 * .askInvestigationQuestion) rather than picking a KPI card. */
export function useAskQuestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (question: string) => askInvestigationQuestion(question),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['investigation'] })
    },
  })
}
