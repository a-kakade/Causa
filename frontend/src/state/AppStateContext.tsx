import { useQueryClient } from '@tanstack/react-query'
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import type { RequesterRole } from '@/types/common'
import type { Persona } from '@/types/narrative'
// Concrete import (not the '@/api' barrel): keeps this file working
// regardless of whether '@/api' currently points at productionApi or the
// offline demoAdapter fallback -- setApiRequesterRole is a no-op-ish setter
// when the production client isn't the active adapter.
import { setApiPeriod, setApiRequesterRole } from '@/api/productionApi/client'
import { setDemoPeriod } from '@/api/demoAdapter/client'
import { type ApiMode, getApiMode, setApiMode as setApiModeGlobal } from '@/api/mode'

/** Every month the backend actually has canonical data for (see
 * api/routes/kpis.py's default timeseries `months` list). Kept here, not
 * fetched, for the same "cosmetic catalog, not governed data" reason
 * kpiRegistry.ts hand-ports the KPI catalog -- the set of governed months
 * doesn't change per-request. */
export const AVAILABLE_PERIODS = [
  '2017-01', '2017-02', '2017-03', '2017-04', '2017-05', '2017-06',
  '2017-07', '2017-08', '2017-09', '2017-10', '2017-11', '2017-12',
]

function monthIndex(period: string): number {
  const [year, month] = period.split('-').map(Number)
  return year * 12 + (month - 1)
}

function monthAtIndex(index: number): string {
  const year = Math.floor(index / 12)
  const month = (index % 12) + 1
  return `${year}-${String(month).padStart(2, '0')}`
}

/** Computes an equal-length range immediately preceding [start, end]
 * (inclusive on both ends). For a single-month range this reduces exactly
 * to previousOf(start), matching the app's original single-month behavior. */
function previousRangeOf(start: string, end: string): { start: string; end: string } {
  const monthCount = monthIndex(end) - monthIndex(start) + 1
  const prevEndIndex = monthIndex(start) - 1
  const prevStartIndex = prevEndIndex - monthCount + 1
  return { start: monthAtIndex(prevStartIndex), end: monthAtIndex(prevEndIndex) }
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
  /** The analysis range shown across KPI cards/trends/overview. Single-month
   * by default (startPeriod === endPeriod), but can span multiple months.
   * previousPeriod/previousStartPeriod/previousEndPeriod are always the
   * equal-length range immediately preceding the current one. `period`/
   * `previousPeriod` are kept as aliases for `endPeriod`/`previousEndPeriod`
   * for components that only care about a single display month. */
  period: string
  previousPeriod: string
  startPeriod: string
  endPeriod: string
  previousStartPeriod: string
  previousEndPeriod: string
  setPeriod: (p: string) => void
  setPeriodRange: (start: string, end: string) => void
  /** Global "Ask your own question" modal (Header's Sparkles button, and any
   * other surface -- e.g. AbstentionState's "Ask a clarifying question" --
   * that wants to hand it a pre-filled prompt instead of duplicating the
   * modal). openAskQuestion(text?) opens it, optionally seeding the textarea. */
  askQuestionOpen: boolean
  askQuestionPrefill: string
  openAskQuestion: (prefill?: string) => void
  closeAskQuestion: () => void
  /** Live = real FastAPI backend (@/api/productionApi). Demo = offline
   * fixture-backed adapter (@/api/demoAdapter), no backend required. See
   * @/api/mode.ts and @/api/index.ts for the actual dispatch. */
  apiMode: ApiMode
  setApiMode: (m: ApiMode) => void
}

const AppStateCtx = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [requesterRole, setRequesterRole] = useState<RequesterRole>('ANALYST')
  const [persona, setPersona] = useState<Persona>('EXECUTIVE')
  const [startPeriod, setStartPeriod] = useState<string>('2017-11')
  const [endPeriod, setEndPeriod] = useState<string>('2017-11')
  const [askQuestionOpen, setAskQuestionOpen] = useState(false)
  const [askQuestionPrefill, setAskQuestionPrefill] = useState('')
  const [apiMode, setApiModeState] = useState<ApiMode>(getApiMode())
  const queryClient = useQueryClient()

  function setApiMode(m: ApiMode) {
    setApiModeGlobal(m)
    setApiModeState(m)
  }

  // Any real data (KPI values, investigations, evidence, ...) cached under
  // the previous mode is from a completely different data source -- refetch
  // everything under the newly selected adapter rather than showing a mix.
  useEffect(() => {
    void queryClient.invalidateQueries()
  }, [apiMode, queryClient])

  function openAskQuestion(prefill = '') {
    setAskQuestionPrefill(prefill)
    setAskQuestionOpen(true)
  }

  function closeAskQuestion() {
    setAskQuestionOpen(false)
  }

  // Every apiFetch call attaches ?requester_role= from productionApi/client's
  // own module-level state -- keep it in sync with this context's role, and
  // invalidate every cached query on a role change so RBAC-filtered data
  // (evidence, segments, graph, ...) actually refetches under the new
  // clearance rather than silently showing the previous role's cached result.
  useEffect(() => {
    setApiRequesterRole(requesterRole)
    void queryClient.invalidateQueries()
  }, [requesterRole, queryClient])

  // Same idea for the period range selector: keep productionApi/client's
  // module state in sync and refetch everything period-scoped (KPI
  // movements, trend reference bands, overview) under the newly selected
  // range.
  const previousRange = useMemo(() => previousRangeOf(startPeriod, endPeriod), [startPeriod, endPeriod])
  useEffect(() => {
    setApiPeriod({ start: startPeriod, end: endPeriod }, previousRange)
    // demoAdapter only has real, backend-computed scenarios for single-month
    // periods (see demoAdapter/kpis.ts, investigations.ts) -- keep its
    // period state in sync too, regardless of which adapter is currently
    // active, so switching to Demo mid-session reflects the period already
    // selected instead of resetting to Nov 2017.
    setDemoPeriod(endPeriod, previousRange.end)
    void queryClient.invalidateQueries()
  }, [startPeriod, endPeriod, previousRange, queryClient])

  function setPeriod(p: string) {
    setStartPeriod(p)
    setEndPeriod(p)
  }

  function setPeriodRange(start: string, end: string) {
    setStartPeriod(start)
    setEndPeriod(monthIndex(end) < monthIndex(start) ? start : end)
  }

  const value = useMemo(
    () => ({
      requesterRole, setRequesterRole, persona, setPersona,
      period: endPeriod, previousPeriod: previousRange.end,
      startPeriod, endPeriod, previousStartPeriod: previousRange.start, previousEndPeriod: previousRange.end,
      setPeriod, setPeriodRange,
      askQuestionOpen, askQuestionPrefill, openAskQuestion, closeAskQuestion,
      apiMode, setApiMode,
    }),
    [requesterRole, persona, startPeriod, endPeriod, previousRange, askQuestionOpen, askQuestionPrefill, apiMode],
  )

  return <AppStateCtx.Provider value={value}>{children}</AppStateCtx.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateCtx)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
