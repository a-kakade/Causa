/**
 * PRODUCTION API — the real HTTP client this app talks to once
 * VITE_API_BASE_URL points at a running `causa/api` FastAPI server.
 *
 * The one place `fetch` happens for the production adapter (mirrors
 * demoAdapter/loadFixture.ts's own "one seam" discipline). The requester
 * role is always sent as a ROLE NAME only (?requester_role=) — the server,
 * never this client, decides what clearance that role gets.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let currentRole: 'ANALYST' | 'EXECUTIVE' | 'INTERNAL' = 'ANALYST'

/** Called once from AppStateContext (or any role-toggle UI) so every
 * subsequent apiFetch call carries the current role without every call site
 * having to pass it explicitly. */
export function setApiRequesterRole(role: 'ANALYST' | 'EXECUTIVE' | 'INTERNAL'): void {
  currentRole = role
}

export function getApiRequesterRole(): string {
  return currentRole
}

// Same one-place-of-truth pattern as the role above, for the analysis
// period range the user picked in the Header's period selector. Defaults
// match the backend's own DEFAULT_CURRENT/DEFAULT_PREVIOUS (routes/kpis.py,
// routes/overview.py) so nothing changes until the user actually picks one.
// A single month is just a range where start === end.
let currentRange = { start: '2017-11', end: '2017-11' }
let previousRange = { start: '2017-10', end: '2017-10' }

export function setApiPeriod(range: { start: string; end: string }, previous: { start: string; end: string }): void {
  currentRange = range
  previousRange = previous
}

export function getApiPeriod(): { period: string; previousPeriod: string; range: { start: string; end: string }; previousRange: { start: string; end: string } } {
  return { period: currentRange.end, previousPeriod: previousRange.end, range: currentRange, previousRange }
}

export async function apiFetch<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const url = new URL(path, BASE_URL)
  if (!url.searchParams.has('requester_role')) {
    url.searchParams.set('requester_role', currentRole)
  }
  if (url.pathname === '/api/overview' || url.pathname === '/api/kpis') {
    // Legacy single-month params (= range end) for back-compat, plus the
    // explicit range so the backend can serve a true multi-month aggregate.
    // Each param is set independently (not gated behind a single "has
    // period already been set" check) so a caller that builds the URL with
    // its own ?period=&previous_period= (getKpiMovements, etc.) still gets
    // the range params attached instead of silently falling back to a
    // single month.
    if (!url.searchParams.has('period')) url.searchParams.set('period', currentRange.end)
    if (!url.searchParams.has('previous_period')) url.searchParams.set('previous_period', previousRange.end)
    if (!url.searchParams.has('start_period')) url.searchParams.set('start_period', currentRange.start)
    if (!url.searchParams.has('end_period')) url.searchParams.set('end_period', currentRange.end)
    if (!url.searchParams.has('previous_start_period')) url.searchParams.set('previous_start_period', previousRange.start)
    if (!url.searchParams.has('previous_end_period')) url.searchParams.set('previous_end_period', previousRange.end)
  }
  const res = await fetch(url.toString(), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body?.error?.message ?? body?.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, `${path} -> ${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: JSON.stringify(body) })
}
