/**
 * DEMO ADAPTER — period state.
 *
 * Mirrors productionApi/client.ts's own module-level period tracking so the
 * offline adapter can also vary its output by the Header's period selector,
 * instead of every demo-mode call silently returning the single canonical
 * Oct->Nov 2017 scenario regardless of what period is selected. Kept as a
 * separate module (not shared with productionApi/client.ts) because the two
 * adapters' "current period" needs to stay in sync independently of which
 * one @/api is actively dispatching to -- AppStateContext updates both on
 * every period change so switching Live<->Demo mid-session never shows a
 * stale period.
 */
let currentPeriod = '2017-11'
let previousPeriod = '2017-10'

export function setDemoPeriod(current: string, previous: string): void {
  currentPeriod = current
  previousPeriod = previous
}

export function getDemoPeriod(): { period: string; previousPeriod: string } {
  return { period: currentPeriod, previousPeriod }
}
