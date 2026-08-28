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

export function titleCase(s: string): string {
  return s
    .replace(/_/g, ' ')
    .split(' ')
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w))
    .join(' ')
}
