import { Area, AreaChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { LoadingState } from '@/components/common/LoadingState'
import { useKpiTrend } from '@/hooks/useKpis'
import { formatMonthLabel, formatNumber } from '@/lib/format'
import { getApiPeriod } from '@/api/productionApi/client'

export function KPITrend({ kpiId, valueFormatter }: { kpiId: string; valueFormatter?: (v: number) => string }) {
  const { data, isLoading } = useKpiTrend(kpiId)
  if (isLoading) return <LoadingState label="Loading trend" />
  if (!data || data.length === 0) return null

  const { period: currentPeriod, previousPeriod } = getApiPeriod()

  const fmt = valueFormatter ?? ((v: number) => formatNumber(Math.round(v)))

  return (
    <div className="h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`kpiTrendFill-${kpiId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
          <ReferenceArea x1={previousPeriod} x2={currentPeriod} fill="var(--color-accent)" fillOpacity={0.06} />
          <XAxis
            dataKey="period"
            tickFormatter={formatMonthLabel}
            tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
            axisLine={{ stroke: 'var(--color-border)' }}
            tickLine={false}
            interval={2}
          />
          <YAxis
            tick={{ fontSize: 10, fill: 'var(--color-ink-faint)' }}
            axisLine={false}
            tickLine={false}
            width={44}
            tickFormatter={(v) => fmt(v)}
          />
          <Tooltip
            contentStyle={{
              background: 'var(--color-ink)',
              border: 'none',
              borderRadius: 6,
              fontSize: 11,
              color: 'var(--color-ink-inverse)',
            }}
            labelFormatter={(l) => formatMonthLabel(String(l))}
            formatter={(v) => [typeof v === 'number' ? fmt(v) : String(v), 'value']}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="var(--color-accent)"
            strokeWidth={2}
            fill={`url(#kpiTrendFill-${kpiId})`}
            connectNulls
            dot={false}
            activeDot={{ r: 3 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
