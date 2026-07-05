"use client"

import { useMemo, useCallback } from "react"
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  Handle,
  Position,
  MarkerType,
} from "reactflow"
import "reactflow/dist/style.css"
import { useResearchStore } from "@/src/lib/store"
import { trustColor } from "./TrustBadge"
import { ExternalLink, FileText, Globe } from "lucide-react"

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
  const isHigh = score >= 81
  const isModerate = score >= 51 && score <= 80

  return (
    <div
      className="rounded-xl border-2 px-3 py-2.5 text-xs shadow-lg"
      style={{
        backgroundColor: `${color}12`,
        borderColor: `${color}80`,
        boxShadow: `0 2px 12px ${color}20`,
        minWidth: 160,
        maxWidth: 200,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!border-0 !w-2 !h-2"
        style={{ backgroundColor: color }}
      />
      {/* Header: type badge + trust label */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider"
          style={{ backgroundColor: `${color}20`, color }}
        >
          <FileText className="h-2.5 w-2.5" />
          Claim
        </span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px] font-bold"
          style={{ backgroundColor: `${color}25`, color }}
        >
          {data.trustLabel}
        </span>
      </div>
      <div className="font-medium text-text-primary leading-tight">
        {data.label.length > 60 ? data.label.slice(0, 57) + "..." : data.label}
      </div>
      {/* Trust score bar */}
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1.5 flex-1 rounded-full bg-bg-tertiary overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${score}%`, backgroundColor: color }}
          />
        </div>
        <span className="text-[10px] font-mono text-text-muted">{score}</span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!border-0 !w-2 !h-2"
        style={{ backgroundColor: color }}
      />
    </div>
  )
}

function SourceNode({
  data,
}: {
  data: { label: string; url: string; toolName?: string }
}) {
  const isCorpus = data.url?.startsWith("corpus://")
  const toolColors: Record<string, string> = {
    arxiv: "#ef4444",
    exa: "#3b82f6",
    serper: "#22c55e",
    tavily: "#eab308",
    github: "#a855f7",
    ddg: "#f97316",
    browser: "#06b6d4",
  }
  const toolColor = toolColors[data.toolName || ""] || "#71717a"

  const handleClick = (e: React.MouseEvent) => {
    // Only redirect if there's a real, non-corpus URL. Corpus entries are
    // internal pgvector references with no web location to open.
    if (data.url && !isCorpus) {
      e.stopPropagation()
      window.open(data.url, "_blank", "noopener,noreferrer")
    } else if (isCorpus) {
      // For corpus sources, show a toast/notification that it's an internal document
      e.stopPropagation()
      alert(`Internal document: ${data.label}\nThis document was uploaded by you and is stored in your private knowledge base.`)
    }
  }

  const hasLink = !!data.url && !isCorpus

  return (
    <div
      onClick={handleClick}
      className={`rounded-lg border px-2.5 py-1.5 text-xs shadow-sm ${
        hasLink ? "cursor-pointer hover:ring-1 hover:ring-white/20 transition-all" : ""
      }`}
      style={{
        borderColor: isCorpus ? "#a855f760" : `${toolColor}60`,
        backgroundColor: isCorpus ? "#a855f710" : `${toolColor}08`,
        color: isCorpus ? "#c084fc" : "#d4d4d8",
        minWidth: 130,
        maxWidth: 170,
      }}
      title={hasLink ? `Open source: ${data.url}` : data.label}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!border-0 !w-1.5 !h-1.5"
        style={{ backgroundColor: toolColor }}
      />
      {/* Header: type badge + click hint */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider"
          style={{ backgroundColor: `${toolColor}20`, color: toolColor }}
        >
          <Globe className="h-2.5 w-2.5" />
          Source
        </span>
        {hasLink && (
          <span className="flex items-center gap-0.5 text-[9px] text-text-muted">
            <ExternalLink className="h-2.5 w-2.5" />
            open
          </span>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <div
          className="h-1.5 w-1.5 flex-shrink-0 rounded-full"
          style={{ backgroundColor: toolColor }}
        />
        <div className="truncate font-medium flex-1 text-text-secondary">
          {data.label.length > 35 ? data.label.slice(0, 32) + "..." : data.label}
        </div>
      </div>
      <div className="mt-1 text-[9px] text-text-muted/80 truncate" title={data.url}>
        {hasLink ? data.url : isCorpus ? `corpus://${data.label}` : ''}
      </div>
      {hasLink && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            window.open(data.url, "_blank", "noopener,noreferrer")
          }}
          className="mt-1.5 flex items-center gap-1 text-[9px] text-accent-blue hover:text-accent-blue/80"
          title="Open in new tab"
        >
          <ExternalLink className="h-2.5 w-2.5" />
          Open
        </button>
      )}
      {data.toolName && (
        <div
          className="mt-1 inline-block rounded px-1 py-0.5 text-[9px] font-semibold uppercase"
          style={{
            backgroundColor: `${toolColor}20`,
            color: toolColor,
          }}
        >
          {data.toolName}
        </div>
      )}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!border-0 !w-1.5 !h-1.5"
        style={{ backgroundColor: toolColor }}
      />
    </div>
  )
}

const nodeTypes = { Claim: ClaimNode, Source: SourceNode }

export function CitationGraph() {
  const citationNodes = useResearchStore((s) => s.citationNodes)
  const citationEdges = useResearchStore((s) => s.citationEdges)

  const { nodes, edges } = useMemo(() => {
    // Separate claims and sources for layout
    const claims = citationNodes.filter((n) => n.type === "Claim")
    const sources = citationNodes.filter((n) => n.type === "Source")

    const claimsPerRow = 4
    const claimSpacingX = 220
    const claimSpacingY = 160

    const sourcesPerRow = 4
    const sourceSpacingX = 190
    const sourceSpacingY = 130

    // Compute base Y for sources dynamically based on claims rows to prevent overlap
    const claimRows = Math.ceil(claims.length / claimsPerRow)
    const baseSourceY = Math.max(220, claimRows * claimSpacingY + 80)

    // Layout: claims on top rows, sources on bottom rows
    const claimNodes: Node[] = claims.map((n, i) => ({
      id: n.id,
      type: "Claim" as const,
      position: {
        x: 40 + (i % claimsPerRow) * claimSpacingX,
        y: Math.floor(i / claimsPerRow) * claimSpacingY,
      },
      data: {
        label: n.label,
        trustScore: n.trustScore,
        trustLabel: n.trustLabel,
      },
    }))

    const sourceNodes: Node[] = sources.map((n, i) => ({
      id: n.id,
      type: "Source" as const,
      position: {
        x: 40 + (i % sourcesPerRow) * sourceSpacingX,
        y: baseSourceY + Math.floor(i / sourcesPerRow) * sourceSpacingY,
      },
      data: {
        label: n.label,
        url: n.url,
        toolName: (n as any).toolName,
        domainAuthority: (n as any).domainAuthority,
      },
    }))

    const allNodes = [...claimNodes, ...sourceNodes]

    const edgeList: Edge[] = citationEdges.map((e, i) => ({
      id: `ce-${i}`,
      source: e.source,
      target: e.target,
      type: "smoothstep" as const,
      animated: false,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: e.type === "SUPPORTS" ? "#22c55e" : e.type === "CONTRADICTS" ? "#ef4444" : "#71717a",
        width: 16,
        height: 16,
      },
      style: {
        stroke: e.type === "SUPPORTS" ? "#22c55e80" : e.type === "CONTRADICTS" ? "#ef444480" : "#52525b80",
        strokeWidth: 1.5,
        opacity: 0.7,
      },
    }))

    return { nodes: allNodes, edges: edgeList }
  }, [citationNodes, citationEdges])

  // Count claims by trust level
  const claims = citationNodes.filter((n) => n.type === "Claim")
  const sources = citationNodes.filter((n) => n.type === "Source")
  const highCount = claims.filter((c) => (c.trustScore ?? 0) >= 81).length
  const modCount = claims.filter((c) => (c.trustScore ?? 0) >= 51 && (c.trustScore ?? 0) <= 80).length
  const lowCount = claims.filter((c) => (c.trustScore ?? 0) <= 50).length

  return (
    <div className="flex h-full flex-col">
      {/* Panel Header */}
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-text-muted">Citations</h3>
          {claims.length > 0 && (
            <span className="rounded-full bg-accent-green/15 px-2 py-0.5 text-[10px] font-bold text-accent-green">
              {claims.length} claims
            </span>
          )}
        </div>
        {claims.length > 0 && (
          <div className="flex items-center gap-2">
            {highCount > 0 && (
              <span className="flex items-center gap-1 text-[10px]">
                <span className="h-2 w-2 rounded-full bg-accent-green" />
                <span className="text-text-muted">{highCount}</span>
              </span>
            )}
            {modCount > 0 && (
              <span className="flex items-center gap-1 text-[10px]">
                <span className="h-2 w-2 rounded-full bg-accent-yellow" />
                <span className="text-text-muted">{modCount}</span>
              </span>
            )}
            {lowCount > 0 && (
              <span className="flex items-center gap-1 text-[10px]">
                <span className="h-2 w-2 rounded-full bg-accent-red" />
                <span className="text-text-muted">{lowCount}</span>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Graph Canvas */}
      {citationNodes.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-bg-tertiary">
            <svg className="h-7 w-7 text-text-muted/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="3" />
              <circle cx="12" cy="5" r="2" />
              <circle cx="12" cy="19" r="2" />
              <circle cx="5" cy="12" r="2" />
              <circle cx="19" cy="12" r="2" />
              <path d="M12 9v6" />
              <path d="M7 12h10" />
            </svg>
          </div>
          <p className="text-sm font-medium text-text-muted">No claims yet</p>
          <p className="text-center text-xs text-text-muted/60 max-w-[200px]">
            Verified claims with trust scores will appear here as the pipeline runs.
            Click a source node to open the original URL.
          </p>
          <div className="mt-2 flex items-center gap-3 rounded-lg bg-bg-tertiary/50 px-3 py-2">
            <span className="flex items-center gap-1 text-[10px]">
              <span className="h-2 w-2 rounded-full bg-accent-green" />
              <span className="text-text-muted">High</span>
            </span>
            <span className="flex items-center gap-1 text-[10px]">
              <span className="h-2 w-2 rounded-full bg-accent-yellow" />
              <span className="text-text-muted">Moderate</span>
            </span>
            <span className="flex items-center gap-1 text-[10px]">
              <span className="h-2 w-2 rounded-full bg-accent-red" />
              <span className="text-text-muted">Low</span>
            </span>
          </div>
        </div>
      ) : (
        <div className="flex-1">
          {sources.length > 0 && (
            <div className="border-b border-border-subtle px-4 py-1.5">
              <span className="text-[10px] text-text-muted">{sources.length} sources cited</span>
            </div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.12 }}
            className="bg-bg-primary"
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#27272a" gap={24} size={1} />
            <Controls
              className="!bg-bg-secondary !border-border-subtle !rounded-lg !shadow-lg"
              showInteractive={false}
            />
          </ReactFlow>
        </div>
      )}
    </div>
  )
}
