import { useQueryClient } from '@tanstack/react-query'
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import type { RequesterRole } from '@/types/common'
import type { Persona } from '@/types/narrative'
// Concrete import (not the '@/api' barrel): keeps this file working
// regardless of whether '@/api' currently points at productionApi or the
// offline demoAdapter fallback -- setApiRequesterRole is a no-op-ish setter
// when the production client isn't the active adapter.
import { setApiPeriod, setApiRequesterRole } from '@/api/productionApi/client'

/** Every month the backend actually has canonical data for (see
 * api/routes/kpis.py's default timeseries `months` list). Kept here, not
 * fetched, for the same "cosmetic catalog, not governed data" reason
 * kpiRegistry.ts hand-ports the KPI catalog -- the set of governed months
 * doesn't change per-request. */
export const AVAILABLE_PERIODS = [
  '2017-01', '2017-02', '2017-03', '2017-04', '2017-05', '2017-06',
  '2017-07', '2017-08', '2017-09', '2017-10', '2017-11', '2017-12',
]

function previousOf(period: string): string {
  const [year, month] = period.split('-').map(Number)
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, '0')}`
}

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
  /** The analysis month shown across KPI cards/trends/overview. previousPeriod
   * is always the prior calendar month, mirroring the backend's own default
   * current/previous pairing. */
  period: string
  previousPeriod: string
  setPeriod: (p: string) => void
}

const AppStateCtx = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [requesterRole, setRequesterRole] = useState<RequesterRole>('ANALYST')
  const [persona, setPersona] = useState<Persona>('EXECUTIVE')
  const [period, setPeriod] = useState<string>('2017-11')
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

  // Same idea for the period selector: keep productionApi/client's module
  // state in sync and refetch everything period-scoped (KPI movements,
  // trend reference bands, overview) under the newly selected month.
  useEffect(() => {
    setApiPeriod(period, previousOf(period))
    void queryClient.invalidateQueries()
  }, [period, queryClient])

  const value = useMemo(
    () => ({ requesterRole, setRequesterRole, persona, setPersona, period, previousPeriod: previousOf(period), setPeriod }),
    [requesterRole, persona, period],
  )

  return <AppStateCtx.Provider value={value}>{children}</AppStateCtx.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateCtx)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
