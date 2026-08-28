import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatSignedCurrency } from '@/lib/format'
import type { PVMBreakdown } from '@/types/driver'

interface WaterfallBar {
  label: string
  start: number
  end: number
  value: number
  kind: 'start' | 'driver' | 'end'
}

function buildBars(pvm: PVMBreakdown, previousValue: number, currentValue: number): WaterfallBar[] {
  let running = previousValue
  const bars: WaterfallBar[] = [{ label: 'Previous', start: 0, end: previousValue, value: previousValue, kind: 'start' }]
  const drivers: [string, number][] = [
    ['Volume', pvm.volumeEffect],
    ['Price', pvm.priceEffect],
    ['Mix', pvm.mixEffect],
  ]
  for (const [label, value] of drivers) {
    const start = value >= 0 ? running : running + value
    const end = value >= 0 ? running + value : running
    bars.push({ label, start, end, value, kind: 'driver' })
    running += value
  }
  bars.push({ label: 'Current', start: 0, end: currentValue, value: currentValue, kind: 'end' })
  return bars
}

export function PVMWaterfall({ pvm, previousValue, currentValue }: { pvm: PVMBreakdown; previousValue: number; currentValue: number }) {
  const bars = buildBars(pvm, previousValue, currentValue)
  const max = Math.max(...bars.map((b) => Math.max(b.start, b.end)))

  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bars} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="20%">
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--color-ink-muted)' }} axisLine={{ stroke: 'var(--color-border)' }} tickLine={false} />
          <YAxis
            domain={[0, max * 1.08]}
            tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
            axisLine={false}
            tickLine={false}
            width={56}
            tickFormatter={(v) => formatSignedCurrency(v).replace('R$', 'R$ ')}
          />
          {/* invisible base to float the driver segments */}
          <Bar dataKey="start" stackId="a" fill="transparent" isAnimationActive={false} />
          <Bar dataKey={(d: WaterfallBar) => Math.abs(d.end - d.start)} stackId="a" radius={[3, 3, 3, 3]} isAnimationActive={false}>
            {bars.map((b, i) => (
              <Cell
                key={i}
                fill={
                  b.kind === 'start' || b.kind === 'end'
                    ? 'var(--color-ink)'
                    : b.value >= 0
                      ? 'var(--color-positive)'
                      : 'var(--color-negative)'
                }
                fillOpacity={b.kind === 'start' || b.kind === 'end' ? 0.85 : 1}
              />
            ))}
          </Bar>
          <Tooltip
            cursor={{ fill: 'var(--color-surface-2)' }}
            contentStyle={{ background: 'var(--color-ink)', border: 'none', borderRadius: 6, fontSize: 11, color: 'var(--color-ink-inverse)' }}
            formatter={(_value, _name, item) => {
              const bar = item.payload as WaterfallBar
              return [formatSignedCurrency(bar.value), bar.label]
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
