import type { EvidenceGraphEdge, EvidenceGraphNode } from '@/types/evidence'
import { apiFetch } from './client'

export interface LaidOutNode extends EvidenceGraphNode {
  x: number
  y: number
}

export interface EvidenceGraphData {
  nodes: LaidOutNode[]
  edges: EvidenceGraphEdge[]
}

interface RawGraphNode {
  id: string
  node_type?: string
  detail?: string
  [key: string]: unknown
}
interface RawGraphEdge {
  source: string
  target: string
  relationship_type?: string
  causal_claim_allowed?: boolean
  [key: string]: unknown
}

/** Real graph nodes/edges from the governed evidence graph
 * (evidence.access_control.filter_graph output via GET /api/evidence/graph/full)
 * -- laid out in a simple radial arrangement here (presentation only, never
 * business data) since the backend graph carries no x/y coordinates. */
export async function getEvidenceGraph(): Promise<EvidenceGraphData> {
  const r = await apiFetch<{ nodes: RawGraphNode[]; edges: RawGraphEdge[] }>('/api/evidence/graph/full')

  const cols = 6
  const nodes: LaidOutNode[] = r.nodes.map((n, i) => ({
    id: n.id,
    label: (n.detail as string) ?? n.id,
    type: (n.node_type ?? 'EVIDENCE') as EvidenceGraphNode['type'],
    value: typeof n.value === 'number' ? (n.value as number) : undefined,
    tier: n.evidence_tier as string | undefined,
    x: (i % cols) * 200 + 40,
    y: Math.floor(i / cols) * 140 + 40,
  }))

  const edges: EvidenceGraphEdge[] = r.edges.map((e) => ({
    source: e.source, target: e.target,
    type: (e.relationship_type ?? 'SUPPORTED_BY') as EvidenceGraphEdge['type'],
    causalClaimAllowed: Boolean(e.causal_claim_allowed),
  }))

  return { nodes, edges }
}
