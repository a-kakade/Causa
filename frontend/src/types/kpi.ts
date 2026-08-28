import type { SecurityClassification } from './common'

/** A governed KPI contract, hand-ported (values only, no logic) from
 * causa/config/kpis.yaml — the source of truth src/kpi/semantic_registry.py loads. */
export interface KPIDef {
  kpiId: string
  name: string
  category: 'primary' | 'supporting'
  description: string
  unit: 'currency_brl' | 'count' | 'days' | 'score_1_5' | 'percent' | 'ratio'
  classification: SecurityClassification
}

/** One computed period value + its movement vs. the previous period.
 * Mirrors ComparisonResult (src/kpi/models.py) as surfaced through the
 * Step 4 evidence fabric's kpi_movement_checks / KPI_MOVEMENT evidence. */
export interface KPIMovement {
  kpiId: string
  period: string
  previousPeriod: string
  currentValue: number
  previousValue: number
  absoluteChange: number
  percentageChange: number
  direction: 'up' | 'down' | 'flat'
  /** true when the movement is favorable for the business (down is good for
   * delivery days; up is good for revenue) — presentation-only, never
   * changes the underlying sign. */
  favorable: boolean
  /** null when the Step 3C materiality/anomaly engine was not run for this
   * KPI in this demo build — the UI must show "not assessed", never guess. */
  materiality: 'CRITICAL' | 'MATERIAL' | 'WATCH' | 'NORMAL' | 'INSUFFICIENT_DATA' | null
  evidenceId?: string
}
