"use client"

import { useMemo, useCallback } from "react"
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  Handle,
  Position,
} from "reactflow"
import "reactflow/dist/style.css"
import { useResearchStore } from "@/lib/store"
import type { AgentStatus } from "@/lib/types"
import { getStatusColor } from "./TrustBadge"

function AgentNodeComponent({
  data,
}: {
  data: {
    label: string
    status: AgentStatus
    model: string
    tier: string
  }
}) {
  const colors = getStatusColor(data.status)
  return (
    <div
      className={`rounded-lg border px-3 py-2 text-xs ${
        data.status === "running" ? "animate-glow" : ""
      }`}
      style={{
        backgroundColor: `${colors.bg}20`,
        borderColor: colors.border,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-transparent"
      />
      <div className="font-medium text-text-primary">{data.label}</div>
      <div className="mt-0.5 text-text-muted">
        {data.model} {data.tier === "reasoning" && "reasoning"}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-transparent"
      />
    </div>
  )
}

const nodeTypes = { agent: AgentNodeComponent }

export function AgentTree() {
  const agents = useResearchStore((s) => s.agents)
  const selectAgent = useResearchStore((s) => s.selectAgent)

  const nodes: Node[] = useMemo(() => {
    const result: Node[] = []
    let searcherIdx = 0
    let browserIdx = 0
    let factCheckerIdx = 0
    let otherIdx = 0

    agents.forEach((agent, id) => {
      let x = 300
      let y = 0

      if (id === "orchestrator") {
        x = 300
        y = 0
      } else if (id === "planner") {
        x = 100
        y = 0
      } else if (id.startsWith("searcher")) {
        x = 50 + searcherIdx * 160
        y = 150
        searcherIdx++
      } else if (id.startsWith("browser")) {
        x = 50 + browserIdx * 160
        y = 280
        browserIdx++
      } else if (id.startsWith("fact_checker")) {
        x = 200 + factCheckerIdx * 160
        y = 410
        factCheckerIdx++
      } else if (id === "critic") {
        x = 450
        y = 280
      } else if (id === "synthesizer") {
        x = 450
        y = 540
      } else if (id === "citation_formatter") {
        x = 450
        y = 670
      } else {
        x = 600 + (otherIdx % 3) * 140
        y = 150 + Math.floor(otherIdx / 3) * 130
        otherIdx++
      }

      result.push({
        id,
        type: "agent",
        position: { x, y },
        data: {
          label: id,
          status: agent.status,
          model: agent.model,
          tier: agent.tier,
        },
      })
    })

    return result
  }, [agents])

  const edges: Edge[] = useMemo(() => {
    const edgeList: Edge[] = []
    const agentIds = Array.from(agents.keys())

    // Connect orchestrator to searchers/browsers
    const searcherIds = agentIds.filter((id) => id.startsWith("searcher"))
    const browserIds = agentIds.filter((id) => id.startsWith("browser"))
    const fcIds = agentIds.filter((id) => id.startsWith("fact_checker"))

    searcherIds.forEach((sid) => {
      edgeList.push({
        id: `orchestrator-${sid}`,
        source: "orchestrator",
        target: sid,
        animated: agents.get(sid)?.status === "running",
        style: { stroke: "#3f3f46", strokeWidth: 2 },
      })
    })

    browserIds.forEach((bid) => {
      edgeList.push({
        id: `orchestrator-${bid}`,
        source: "orchestrator",
        target: bid,
        animated: agents.get(bid)?.status === "running",
        style: { stroke: "#3f3f46", strokeWidth: 2 },
      })
    })

    fcIds.forEach((fid) => {
      edgeList.push({
        id: `orchestrator-${fid}`,
        source: "orchestrator",
        target: fid,
        animated: agents.get(fid)?.status === "running",
        style: { stroke: "#3f3f46", strokeWidth: 2 },
      })
    })

    return edgeList
  }, [agents])

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      selectAgent(node.id)
    },
    [selectAgent]
  )

  if (agents.size === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-sm text-text-muted">
        <div className="mb-3 text-4xl">F</div>
        <p>Start a research query to see agents in action</p>
        <p className="mt-1 text-xs text-text-muted">
          The agent tree will populate in real-time
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
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        defaultEdgeOptions={{ animated: false }}
        className="bg-bg-primary"
      >
        <Background color="#27272a" gap={16} />
        <Controls className="!bg-bg-secondary !border-border-subtle" />
        <MiniMap
          className="!bg-bg-secondary !border-border-subtle"
          nodeColor={(n) => getStatusColor((n.data?.status as AgentStatus) || "idle").bg}
        />
      </ReactFlow>
    </div>
  )
}
