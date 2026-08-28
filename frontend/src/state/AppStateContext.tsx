import { createContext, type ReactNode, useContext, useMemo, useState } from 'react'
import type { RequesterRole } from '@/types/common'
import type { Persona } from '@/types/narrative'

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
