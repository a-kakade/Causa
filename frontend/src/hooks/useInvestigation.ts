import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import { askInvestigationQuestion } from '@/api'
import { getInvestigation } from '@/api'
import { useAppState } from '@/state/AppStateContext'
import type { RequesterRole } from '@/types/common'

/** Maps the app's 3-way RBAC role onto the 2 real investigation runs the
 * backend actually produced (analyst_investigation / executive_investigation)
 * — INTERNAL reuses the analyst run (it is the higher-clearance superset). */
function runFor(role: RequesterRole): 'ANALYST' | 'EXECUTIVE' {
  return role === 'EXECUTIVE' ? 'EXECUTIVE' : 'ANALYST'
}

export function useCurrentInvestigation() {
  const { requesterRole } = useAppState()
  const role = runFor(requesterRole)
  return useQuery({ queryKey: ['investigation', role], queryFn: () => getInvestigation(role) })
}

export function useInvestigationByRole(role: 'ANALYST' | 'EXECUTIVE') {
  return useQuery({ queryKey: ['investigation', role], queryFn: () => getInvestigation(role) })
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
