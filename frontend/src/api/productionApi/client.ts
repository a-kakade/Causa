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

export async function apiFetch<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const url = new URL(path, BASE_URL)
  if (!url.searchParams.has('requester_role')) {
    url.searchParams.set('requester_role', currentRole)
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
