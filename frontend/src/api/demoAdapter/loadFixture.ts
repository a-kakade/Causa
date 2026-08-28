/**
 * DEMO ADAPTER — fixture loader.
 *
 * There is no HTTP API in the CAUSA backend today (it's an in-process Python
 * Tool Gateway + a script entrypoint — see docs/FRONTEND_ARCHITECTURE.md).
 * Every value this app renders is fetched from a static copy of a REAL
 * backend-computed validation report (causa/reports/step*_validation.json),
 * served from /public/fixtures. Nothing here is hand-authored data.
 *
 * This file is the ONLY place that touches `fetch` for fixtures — keeping
 * the seam narrow means swapping in a real `productionApi` later never
 * touches a page or component.
 */

export const DEMO_MODE = true

const cache = new Map<string, Promise<unknown>>()

export function loadFixture<T = unknown>(name: string): Promise<T> {
  const existing = cache.get(name)
  if (existing) return existing as Promise<T>
  const promise = fetch(`/fixtures/${name}.json`).then((res) => {
    if (!res.ok) throw new Error(`Fixture not found: ${name} (${res.status})`)
    return res.json() as Promise<T>
  })
  cache.set(name, promise)
  return promise as Promise<T>
}
