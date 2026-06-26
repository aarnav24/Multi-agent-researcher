"use client"

import { useMemo } from "react"
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  Handle,
  Position,
} from "reactflow"
import "reactflow/dist/style.css"
import { useResearchStore } from "@/lib/store"
import { trustColor } from "./TrustBadge"

function ClaimNode({
  data,
}: {
  data: {
    label: string
    trustScore: number
    trustLabel: string
  }
}) {
  const score = data.trustScore
  const color = trustColor(score)
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs"
      style={{
        backgroundColor: `${color}15`,
        borderColor: `${color}60`,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-transparent"
      />
      <div className="max-w-[180px] truncate font-medium text-text-primary">
        {data.label}
      </div>
      <div className="mt-1 flex items-center gap-1">
        <div className="h-1.5 flex-1 rounded-full bg-bg-tertiary">
          <div
            className="h-1.5 rounded-full transition-all"
            style={{ width: `${score}%`, backgroundColor: color }}
          />
        </div>
        <span style={{ color }} className="text-[10px] font-medium">
          {data.trustLabel}
        </span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-transparent"
      />
    </div>
  )
}

function SourceNode({
  data,
}: {
  data: { label: string; url: string }
}) {
  const isCorpus = data.url?.startsWith("corpus://")
  return (
    <div
      className="rounded border px-2 py-1 text-xs"
      style={{
        borderColor: isCorpus ? "#a855f7" : "#27272a",
        backgroundColor: isCorpus ? "#a855f715" : "#18181b",
        color: isCorpus ? "#c084fc" : "#a1a1aa",
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-transparent"
      />
      <div className="max-w-[140px] truncate">
        {isCorpus && " "}
        {data.label}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-transparent"
      />
    </div>
  )
}

const nodeTypes = { Claim: ClaimNode, Source: SourceNode }

export function CitationGraph() {
  const citationNodes = useResearchStore((s) => s.citationNodes)
  const citationEdges = useResearchStore((s) => s.citationEdges)

  const nodes: Node[] = useMemo(() => {
    return citationNodes.map((n, i) => ({
      id: n.id,
      type: n.type,
      position: {
        x: (i % 4) * 200,
        y: Math.floor(i / 4) * 120,
      },
      data: {
        label: n.label,
        trustScore: n.trustScore,
        trustLabel: n.trustLabel,
        url: n.url,
      },
    }))
  }, [citationNodes])

  const edges: Edge[] = useMemo(() => {
    return citationEdges.map((e, i) => ({
      id: `ce-${i}`,
      source: e.source,
      target: e.target,
      animated: true,
      style: {
        stroke: e.type === "SUPPORTS" ? "#22c55e" : "#ef4444",
        strokeWidth: 1.5,
      },
    }))
  }, [citationEdges])

  if (citationNodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-sm text-text-muted">
        <div className="mb-2 text-xl font-medium">Citation Graph</div>
        <p>Claims will appear here as they are verified...</p>
        <p className="mt-1 text-xs">
          Trust scores: Green = HIGH | Yellow = MODERATE | Red = LOW
        </p>
      </div>
    )
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        className="bg-bg-primary"
      >
        <Background color="#27272a" gap={16} />
        <Controls className="!bg-bg-secondary !border-border-subtle" />
      </ReactFlow>
    </div>
  )
}
