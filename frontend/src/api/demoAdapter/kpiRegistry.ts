import type { KPIDef } from '@/types/kpi'

/**
 * Hand-ported (values only, no formulas/logic) from causa/config/kpis.yaml —
 * the governed KPI semantic layer src/kpi/semantic_registry.py loads. Only
 * name/category/description/unit/classification are reproduced; the actual
 * computed values always come from the fixture reports, never from here.
 */
export const KPI_REGISTRY: KPIDef[] = [
  {
    kpiId: 'revenue',
    name: 'Revenue',
    category: 'primary',
    description: 'Total realized transaction value at order-item price grain, summed to order grain.',
    unit: 'currency_brl',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'orders',
    name: 'Orders',
    category: 'primary',
    description: 'Count of distinct orders placed.',
    unit: 'count',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'aov',
    name: 'Average Order Value',
    category: 'primary',
    description: 'Average revenue per order, order-weighted.',
    unit: 'currency_brl',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'avg_delivery_days',
    name: 'Avg. Delivery Days',
    category: 'primary',
    description: 'Mean days from order purchase to customer delivery, valid rows only.',
    unit: 'days',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'avg_review_score',
    name: 'Avg. Review Score',
    category: 'primary',
    description: 'Mean customer satisfaction rating (1-5 stars), order-level representative variant.',
    unit: 'score_1_5',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'freight_revenue',
    name: 'Freight Revenue',
    category: 'supporting',
    description: 'Total shipping cost charged to customers, order-item grain summed to order grain.',
    unit: 'currency_brl',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'review_volume',
    name: 'Review Volume',
    category: 'supporting',
    description: 'Count of review records submitted, review grain.',
    unit: 'count',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'on_time_delivery_rate',
    name: 'On-Time Delivery Rate',
    category: 'supporting',
    description: 'Share of valid-delivery orders delivered on or before the estimated delivery date.',
    unit: 'percent',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'quantity_sold',
    name: 'Quantity Sold',
    category: 'supporting',
    description: 'Count of order-item units sold, line-item grain.',
    unit: 'count',
    classification: 'PUBLIC_ANALYTICAL',
  },
  {
    kpiId: 'repeat_purchase_rate',
    name: 'Repeat Purchase Rate',
    category: 'supporting',
    description: 'Share of distinct customers (by customer_unique_id) who placed 2+ orders.',
    unit: 'percent',
    classification: 'PUBLIC_ANALYTICAL',
  },
]

export function kpiDef(kpiId: string): KPIDef | undefined {
  return KPI_REGISTRY.find((k) => k.kpiId === kpiId)
}

/** KPIs a KPI-movement waterfall/trend view exists for in this demo build
 * (Oct -> Nov 2017 Olist scenario). */
export const DEMO_PERIOD_CURRENT = '2017-11'
export const DEMO_PERIOD_PREVIOUS = '2017-10'
