import type { EvidenceGraphEdge, EvidenceGraphNode } from '@/types/evidence'
import { getCausalResults } from './causal'
import { getDriverDecomposition } from './drivers'
import { getKpiMovement } from './kpis'

export interface LaidOutNode extends EvidenceGraphNode {
  x: number
  y: number
}

export interface EvidenceGraphData {
  nodes: LaidOutNode[]
  edges: EvidenceGraphEdge[]
}

/**
 * Composes the evidence graph from the SAME real fixture-backed data the
 * rest of the app renders (PVM, KPI movements, causal results) — there is
 * no separate "graph export" in the backend reports, so this is a
 * presentation-layer assembly of real numbers into a graph shape, not a
 * fabricated structure. Positions are layout only, never business data.
 */
export async function getEvidenceGraph(): Promise<EvidenceGraphData> {
  const [decomposition, revenue, causalResults] = await Promise.all([
    getDriverDecomposition(true),
    getKpiMovement('revenue'),
    getCausalResults(),
  ])

  const c1 = causalResults.find((c) => c.hypothesisId.startsWith('C1'))
  const c3 = causalResults.find((c) => c.hypothesisId.startsWith('C3'))

  const nodes: LaidOutNode[] = [
    { id: 'kpi_revenue', label: 'Revenue', type: 'KPI', x: 420, y: 0 },
    {
      id: 'movement',
      label: `Nov 2017 Movement ${revenue ? (revenue.percentageChange > 0 ? '+' : '') + revenue.percentageChange.toFixed(1) + '%' : ''}`,
      type: 'MOVEMENT',
      x: 420,
      y: 100,
    },

    { id: 'driver_volume', label: 'Volume', type: 'DRIVER', value: decomposition.pvm.volumeEffect, x: 180, y: 210 },
    { id: 'driver_price', label: 'Price', type: 'DRIVER', value: decomposition.pvm.priceEffect, x: 420, y: 210 },
    { id: 'driver_mix', label: 'Mix', type: 'DRIVER', value: decomposition.pvm.mixEffect, x: 660, y: 210 },

    ...decomposition.topCategoryContributions.slice(0, 3).map(
      (c, i): LaidOutNode => ({
        id: `segment_${c.segment}`,
        label: c.segment,
        type: 'SEGMENT',
        value: c.contributionValue,
        x: 40 + i * 170,
        y: 320,
      }),
    ),

    { id: 'kpi_orders', label: 'Orders', type: 'KPI', x: 900, y: 100 },
    { id: 'kpi_aov', label: 'AOV', type: 'KPI', x: 1040, y: 160 },
    { id: 'kpi_delivery', label: 'Delivery Days', type: 'KPI', x: 900, y: 220 },
    { id: 'kpi_review', label: 'Review Score', type: 'KPI', x: 900, y: 320 },
    { id: 'reviews', label: 'Customer Reviews', type: 'EVIDENCE', x: 900, y: 420 },

    {
      id: 'causal_c1',
      label: `C1 · PVM (${c1?.evidenceTier ?? 'T2_ARITHMETIC'})`,
      type: 'CAUSAL_ANALYSIS',
      tier: c1?.evidenceTier,
      x: 180,
      y: 420,
    },
    {
      id: 'causal_c3',
      label: `C3 · Delivery/Review (${c3?.evidenceTier ?? 'T1_DESCRIPTIVE'})`,
      type: 'CAUSAL_ANALYSIS',
      tier: c3?.evidenceTier,
      x: 660,
      y: 420,
    },

    { id: 'confidence', label: 'Confidence: ABSTAIN', type: 'CONFIDENCE', x: 420, y: 520 },
  ]

  const edges: EvidenceGraphEdge[] = [
    { source: 'kpi_revenue', target: 'movement', type: 'HAS_MOVEMENT', causalClaimAllowed: false },
    { source: 'movement', target: 'driver_volume', type: 'EXPLAINED_BY', causalClaimAllowed: false },
    { source: 'movement', target: 'driver_price', type: 'EXPLAINED_BY', causalClaimAllowed: false },
    { source: 'movement', target: 'driver_mix', type: 'EXPLAINED_BY', causalClaimAllowed: false },

    ...decomposition.topCategoryContributions.slice(0, 3).map(
      (c): EvidenceGraphEdge => ({
        source: c.contributionValue >= 0 ? 'driver_volume' : 'driver_mix',
        target: `segment_${c.segment}`,
        type: 'DERIVED_FROM',
        causalClaimAllowed: false,
      }),
    ),

    { source: 'movement', target: 'kpi_orders', type: 'ASSOCIATED_WITH', causalClaimAllowed: false },
    { source: 'movement', target: 'kpi_aov', type: 'ASSOCIATED_WITH', causalClaimAllowed: false },
    { source: 'movement', target: 'kpi_delivery', type: 'ASSOCIATED_WITH', causalClaimAllowed: false },
    { source: 'kpi_delivery', target: 'kpi_review', type: 'ASSOCIATED_WITH', causalClaimAllowed: false },
    { source: 'kpi_review', target: 'reviews', type: 'SUPPORTED_BY', causalClaimAllowed: false },

    { source: 'driver_volume', target: 'causal_c1', type: 'TESTED_BY', causalClaimAllowed: c1?.causalClaimAllowed ?? false },
    { source: 'kpi_delivery', target: 'causal_c3', type: 'TESTED_BY', causalClaimAllowed: c3?.causalClaimAllowed ?? false },
    { source: 'kpi_review', target: 'causal_c3', type: 'TESTED_BY', causalClaimAllowed: c3?.causalClaimAllowed ?? false },

    { source: 'causal_c1', target: 'confidence', type: 'HAS_CONFIDENCE', causalClaimAllowed: false },
    { source: 'causal_c3', target: 'confidence', type: 'HAS_CONFIDENCE', causalClaimAllowed: false },
  ]

  return { nodes, edges }
}
