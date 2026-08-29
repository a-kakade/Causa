import { useMemo } from 'react'
import ReactFlow, { Background, type Edge, MarkerType, type Node, Position } from 'reactflow'
import 'reactflow/dist/style.css'
import { formatSignedCurrency } from '@/lib/format'
import type { EvidenceGraphData } from '@/api'

const NODE_COLOR: Record<string, string> = {
  KPI: 'var(--color-ink)',
  MOVEMENT: 'var(--color-accent)',
  DRIVER: 'var(--color-accent)',
  SEGMENT: 'var(--color-ink-muted)',
  EVIDENCE: 'var(--color-warning)',
  CAUSAL_ANALYSIS: 'var(--color-negative)',
  CONFIDENCE: 'var(--color-confidence-abstain)',
}

const EDGE_COLOR: Record<string, string> = {
  CONTRADICTS: 'var(--color-negative)',
  TESTED_BY: 'var(--color-negative)',
  ASSOCIATED_WITH: 'var(--color-ink-faint)',
}

export function EvidenceGraph({ data }: { data: EvidenceGraphData }) {
  const nodes: Node[] = useMemo(
    () =>
      data.nodes.map((n) => ({
        id: n.id,
        position: { x: n.x, y: n.y },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        data: { label: n.value !== undefined ? `${n.label}\n${formatSignedCurrency(n.value)}` : n.label },
        style: {
          border: `1.5px solid ${NODE_COLOR[n.type] ?? 'var(--color-border-strong)'}`,
          borderRadius: 7,
          background: 'var(--color-surface)',
          color: 'var(--color-ink)',
          fontSize: 11,
          fontWeight: 600,
          padding: '6px 10px',
          whiteSpace: 'pre-line',
          textAlign: 'center',
          width: 148,
        },
      })),
    [data.nodes],
  )

  const edges: Edge[] = useMemo(
    () =>
      data.edges.map((e, i) => ({
        id: `${e.source}-${e.target}-${i}`,
        source: e.source,
        target: e.target,
        label: e.type.replaceAll('_', ' ').toLowerCase(),
        labelStyle: { fontSize: 9, fill: 'var(--color-ink-faint)' },
        labelBgStyle: { fill: 'var(--color-surface)' },
        style: { stroke: EDGE_COLOR[e.type] ?? 'var(--color-border-strong)', strokeWidth: 1.3 },
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR[e.type] ?? 'var(--color-border-strong)' },
        animated: e.type === 'TESTED_BY',
      })),
    [data.edges],
  )

  return (
    <div className="h-[560px] rounded-(--radius-md) border border-(--color-border) bg-(--color-surface-2)">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }} nodesDraggable={false} nodesConnectable={false}>
        <Background color="var(--color-border)" gap={20} size={1} />
      </ReactFlow>
    </div>
  )
}
