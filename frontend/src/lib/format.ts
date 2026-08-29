/** Formatting helpers. These format real numbers passed in — they never
 * invent or round in a way that changes the underlying magnitude beyond
 * standard display precision. */

const brl = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
const brlCompact = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 2,
})
const number = new Intl.NumberFormat('en-US')
const percent1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

export function formatCurrency(value: number): string {
  return brl.format(value)
}

export function formatCurrencyCompact(value: number): string {
  return brlCompact.format(value)
}

export function formatNumber(value: number): string {
  return number.format(value)
}

export function formatPercent(value: number, opts: { signed?: boolean } = {}): string {
  const sign = opts.signed && value > 0 ? '+' : ''
  return `${sign}${percent1.format(value)}%`
}

export function formatSignedCurrency(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${brl.format(Math.abs(value))}`
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: '2-digit' })
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function formatMonthLabel(period: string): string {
  // "2017-11" -> "Nov 2017"
  const [y, m] = period.split('-')
  if (!y || !m) return period
  const d = new Date(Number(y), Number(m) - 1, 1)
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

/** Kept in sync with KPIDef['unit'] (types/kpi.ts) without importing it, to
 * avoid coupling this low-level formatting module to the KPI type layer. */
export type KPIUnit = 'currency_brl' | 'count' | 'days' | 'score_1_5' | 'percent' | 'ratio'

/** Formats a raw KPI value for display according to its governed unit.
 * 'percent'/'ratio' values arrive from the backend as a 0-1 fraction (e.g.
 * 0.0118 for a 1.18% repeat purchase rate) -- NOT already scaled to 0-100,
 * unlike percentage_change/movement deltas, which the backend already
 * returns pre-scaled (e.g. -19.7 for -19.7%). Mixing the two up is what
 * makes a percent KPI render as "0.0%" or a raw "0.012". */
export function formatKpiValue(value: number, unit: KPIUnit): string {
  if (Number.isNaN(value)) return '—'
  switch (unit) {
    case 'currency_brl':
      return formatCurrency(value)
    case 'count':
      return formatNumber(Math.round(value))
    case 'days':
      return `${value.toFixed(2)} days`
    case 'score_1_5':
      return value.toFixed(2)
    case 'percent':
    case 'ratio':
      return formatPercent(value * 100)
    default:
      return formatNumber(value)
  }
}

/** Same unit-awareness as formatKpiValue, but for a signed delta (e.g. "What
 * changed" / "Change:" rows) -- never assumes currency. */
export function formatKpiChange(value: number, unit: KPIUnit): string {
  if (Number.isNaN(value)) return '—'
  if (unit === 'currency_brl') return formatSignedCurrency(value)
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${formatKpiValue(Math.abs(value), unit)}`
}

export function titleCase(s: string): string {
  return s
    .replace(/_/g, ' ')
    .split(' ')
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w))
    .join(' ')
}
