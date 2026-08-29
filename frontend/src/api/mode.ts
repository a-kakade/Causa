/**
 * api/mode.ts — the runtime Live/Demo switch.
 *
 * `@/api` (index.ts) dispatches every call to either productionApi (real
 * backend, real Groq/FakeLLMClient investigations) or demoAdapter (offline,
 * reads the static /public/fixtures copy of a real validated run) based on
 * the mode held here. Kept as a plain module -- not React state -- because
 * index.ts's dispatch functions are called from outside any component tree
 * (react-query's queryFn), so they need a synchronous, non-hook way to read
 * "which adapter right now". AppStateContext wraps this in reactive state
 * for the UI toggle and handles invalidating cached queries on switch.
 */
export type ApiMode = 'live' | 'demo'

const STORAGE_KEY = 'causa-api-mode'

function readInitialMode(): ApiMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'demo' ? 'demo' : 'live'
  } catch {
    return 'live'
  }
}

let mode: ApiMode = readInitialMode()
const listeners = new Set<(m: ApiMode) => void>()

export function getApiMode(): ApiMode {
  return mode
}

export function setApiMode(next: ApiMode): void {
  if (next === mode) return
  mode = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // best-effort persistence only -- a private-browsing session simply
    // resets to 'live' next load, which is a safe default.
  }
  listeners.forEach((l) => l(next))
}

/** Subscribes to mode changes; returns an unsubscribe function. Used by
 * AppStateContext to mirror this module's state into React. */
export function subscribeApiMode(listener: (m: ApiMode) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
