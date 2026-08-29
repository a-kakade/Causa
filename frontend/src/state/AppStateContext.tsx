import { useQueryClient } from '@tanstack/react-query'
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import type { RequesterRole } from '@/types/common'
import type { Persona } from '@/types/narrative'
// Concrete import (not the '@/api' barrel): keeps this file working
// regardless of whether '@/api' currently points at productionApi or the
// offline demoAdapter fallback -- setApiRequesterRole is a no-op-ish setter
// when the production client isn't the active adapter.
import { setApiRequesterRole } from '@/api/productionApi/client'

interface AppState {
  /** Drives RBAC/clearance throughout the app, and which real investigation
   * run (analyst_investigation vs executive_investigation) is shown. */
  requesterRole: RequesterRole
  setRequesterRole: (r: RequesterRole) => void
  /** Drives which real KPIStory (Step 8) is shown on the narrative surfaces —
   * independent of requesterRole, since the backend generates a narrative
   * per persona regardless of who's asking. */
  persona: Persona
  setPersona: (p: Persona) => void
}

const AppStateCtx = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [requesterRole, setRequesterRole] = useState<RequesterRole>('ANALYST')
  const [persona, setPersona] = useState<Persona>('EXECUTIVE')
  const queryClient = useQueryClient()

  // Every apiFetch call attaches ?requester_role= from productionApi/client's
  // own module-level state -- keep it in sync with this context's role, and
  // invalidate every cached query on a role change so RBAC-filtered data
  // (evidence, segments, graph, ...) actually refetches under the new
  // clearance rather than silently showing the previous role's cached result.
  useEffect(() => {
    setApiRequesterRole(requesterRole)
    void queryClient.invalidateQueries()
  }, [requesterRole, queryClient])

  const value = useMemo(
    () => ({ requesterRole, setRequesterRole, persona, setPersona }),
    [requesterRole, persona],
  )

  return <AppStateCtx.Provider value={value}>{children}</AppStateCtx.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateCtx)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
