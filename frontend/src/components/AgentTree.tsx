"use client"

import { useMemo, useCallback, useState } from "react"
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  Handle,
  Position,
  MarkerType,
} from "reactflow"
import "reactflow/dist/style.css"
import { useResearchStore } from "@/src/lib/store"
import type { AgentStatus } from "@/src/lib/types"
import { getStatusColor } from "./TrustBadge"

function AgentNodeComponent({ data }: { data: { label: string; status: AgentStatus; model: string; tier: string; question?: string } }) {
  const colors = getStatusColor(data.status)
  const isRunning = data.status === "running"
  return (
    <div
      className={`rounded-xl border-2 px-3 py-2 text-xs shadow-lg transition-all ${isRunning ? "animate-glow scale-105" : ""}`}
      style={{
        backgroundColor: `${colors.bg}15`,
        borderColor: colors.border,
        boxShadow: isRunning ? `0 0 20px ${colors.bg}40` : `0 2px 8px rgba(0,0,0,0.3)`,
        minWidth: 110,
      }}
    >
      <Handle type="target" position={Position.Top} className="!border-0 !w-2 !h-2" style={{ backgroundColor: colors.bg }} />
      <div className="flex items-center gap-1.5">
        <div className="h-2 w-2 rounded-full" style={{ backgroundColor: colors.bg }} />
        <span className="font-semibold text-text-primary truncate max-w-[90px]">{data.label}</span>
      </div>
      <div className="mt-1 flex items-center gap-1">
        <span className="rounded px-1 py-0.5 text-[9px] font-bold" style={{ backgroundColor: data.tier === "reasoning" ? "#a855f720" : "#3b82f620", color: data.tier === "reasoning" ? "#c084fc" : "#60a5fa" }}>
          {data.tier === "reasoning" ? "REASON" : "FAST"}
        </span>
      </div>
      <Handle type="source" position={Position.Bottom} className="!border-0 !w-2 !h-2" style={{ backgroundColor: colors.bg }} />
    </div>
  )
}

const nodeTypes = { agent: AgentNodeComponent }

export function AgentTree() {
  const agents = useResearchStore((s) => s.agents)
  const selectAgent = useResearchStore((s) => s.selectAgent)
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null)

  const nodes: Node[] = useMemo(() => {
    const result: Node[] = []
    // Only true worker nodes (with numeric suffix) belong in the workers column.
    // Filter out compound node names like "searchers"/"browsers"/"fact_checker"
    // to avoid showing the same agent in both pipeline and workers.
    const searchers = Array.from(agents.entries()).filter(([id]) => /^searcher-\d+$/.test(id))
    const browsers = Array.from(agents.entries()).filter(([id]) => /^browser-\d+$/.test(id))
    const factCheckers = Array.from(agents.entries()).filter(([id]) => /^fact_checker-\d+$/.test(id))
    const others = Array.from(agents.entries()).filter(([id]) =>
      !["searcher", "browser", "fact_checker"].some((p) => id.startsWith(p)) &&
      !["system"].includes(id)
    )

    // Dynamic grid layout: Left = pipeline flow, Right = workers
    const pipelineX = 80
    const cols = 3
    const colWidth = 140
    const rowHeight = 85

    const searcherRows = Math.max(1, Math.ceil(searchers.length / cols))
    const browserRows = Math.max(1, Math.ceil(browsers.length / cols))
    const fcRows = Math.max(1, Math.ceil(factCheckers.length / cols))

    const plannerY = 30
    const orchestratorY = 140
    const criticY = orchestratorY + searcherRows * rowHeight + 40
    const synthesizerY = criticY + browserRows * rowHeight + 40
    const formatterY = synthesizerY + fcRows * rowHeight + 40

    const pipelinePositions: Record<string, number> = {
      planner: plannerY,
      orchestrator: orchestratorY,
      critic: criticY,
      synthesizer: synthesizerY,
      citation_formatter: formatterY,
    }

    const pipelineAgents = ["planner", "orchestrator", "critic", "synthesizer", "citation_formatter"]
    pipelineAgents.forEach((name) => {
      const agent = agents.get(name)
      if (agent) {
        result.push({
          id: name,
          type: "agent",
          position: { x: pipelineX, y: pipelinePositions[name] },
          data: { label: name.replace(/_/g, " "), status: agent.status, model: agent.model, tier: agent.tier },
        })
      }
    })

    // Helper to create friendly labels
    const labelFor = (id: string, index: number) => {
      if (id.startsWith("searcher")) return `Searcher-${index + 1}`
      if (id.startsWith("browser")) return `Browser-${index + 1}`
      if (id.startsWith("fact_checker")) return `Fact-Checker-${index + 1}`
      return id.replace(/_/g, " ")
    }

    // Workers: Searchers
    searchers.forEach(([id, agent], i) => {
      const row = Math.floor(i / cols)
      const col = i % cols
      result.push({
        id, type: "agent",
        position: { x: 260 + col * colWidth, y: orchestratorY + row * rowHeight },
        data: { label: labelFor(id, i), status: agent.status, model: agent.model, tier: agent.tier, question: agent.question },
      })
    })

    // Workers: Browsers
    browsers.forEach(([id, agent], i) => {
      const row = Math.floor(i / cols)
      const col = i % cols
      result.push({
        id, type: "agent",
        position: { x: 260 + col * colWidth, y: criticY + row * rowHeight },
        data: { label: labelFor(id, i), status: agent.status, model: agent.model, tier: agent.tier, question: agent.question },
      })
    })

    // Workers: Fact Checkers
    factCheckers.forEach(([id, agent], i) => {
      const row = Math.floor(i / cols)
      const col = i % cols
      result.push({
        id, type: "agent",
        position: { x: 260 + col * colWidth, y: synthesizerY + row * rowHeight },
        data: { label: labelFor(id, i), status: agent.status, model: agent.model, tier: agent.tier },
      })
    })

    return result
  }, [agents])

  const edges = useMemo(() => {
    const edgeList: Edge[] = []
    const agentIds = Array.from(agents.keys())
    const searcherIds = agentIds.filter((id) => /^searcher-\d+$/.test(id))
    const browserIds = agentIds.filter((id) => /^browser-\d+$/.test(id))
    const fcIds = agentIds.filter((id) => /^fact_checker-\d+$/.test(id))

    const makeEdge = (id: string, source: string, target: string, status?: string): Edge => {
      const isSelected = selectedEdge === id
      const strokeColor = isSelected ? "#3b82f6" : status === "completed" ? "#22c55e80" : status === "running" ? "#eab308" : "#52525b80"
      return {
        id, source, target,
        type: "smoothstep",
        animated: status === "running" || isSelected,
        markerEnd: { type: MarkerType.ArrowClosed, color: isSelected ? "#3b82f6" : status === "completed" ? "#22c55e" : status === "running" ? "#eab308" : "#52525b", width: 16, height: 16 },
        style: { stroke: strokeColor, strokeWidth: isSelected ? 3 : status === "running" ? 2.5 : 1.5 },
      }
    }

    // Pipeline flow: planner → orchestrator → critic → synthesizer → citation_formatter
    const pipeline = ["planner", "orchestrator", "critic", "synthesizer", "citation_formatter"]
    for (let i = 0; i < pipeline.length - 1; i++) {
      if (agents.get(pipeline[i]) && agents.get(pipeline[i + 1])) {
        edgeList.push(makeEdge(`${pipeline[i]}-${pipeline[i + 1]}`, pipeline[i], pipeline[i + 1], agents.get(pipeline[i + 1])?.status))
      }
    }

    // Workers → Orchestrator (all workers connect to orchestrator)
    searcherIds.forEach((sid) => {
      edgeList.push(makeEdge(`orch-${sid}`, "orchestrator", sid, agents.get(sid)?.status))
    })
    browserIds.forEach((bid) => {
      edgeList.push(makeEdge(`orch-${bid}`, "orchestrator", bid, agents.get(bid)?.status))
    })

    // Workers → Critic
    searcherIds.forEach((sid) => {
      if (agents.get("critic")) edgeList.push(makeEdge(`${sid}-critic`, sid, "critic", agents.get("critic")?.status))
    })
    browserIds.forEach((bid) => {
      if (agents.get("critic")) edgeList.push(makeEdge(`${bid}-critic`, bid, "critic", agents.get("critic")?.status))
    })

    // Fact Checkers → Synthesizer
    fcIds.forEach((fid) => {
      if (agents.get("synthesizer")) edgeList.push(makeEdge(`${fid}-synth`, fid, "synthesizer", agents.get("synthesizer")?.status))
    })

    return edgeList
  }, [agents, selectedEdge])

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => { selectAgent(node.id) }, [selectAgent])
  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelectedEdge(prev => prev === edge.id ? null : edge.id)
  }, [])

  // Count agents by status
  const runningCount = Array.from(agents.values()).filter((a) => a.status === "running").length
  const completedCount = Array.from(agents.values()).filter((a) => a.status === "completed").length

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-text-muted">Agent Tree</h3>
          {agents.size > 0 && <span className="rounded-full bg-accent-blue/15 px-2 py-0.5 text-[10px] font-bold text-accent-blue">{agents.size}</span>}
        </div>
        {agents.size > 0 && (
          <div className="flex items-center gap-2">
            {runningCount > 0 && <span className="flex items-center gap-1 text-[10px]"><span className="h-2 w-2 rounded-full bg-accent-yellow animate-pulse" /><span className="text-text-muted">{runningCount}</span></span>}
            {completedCount > 0 && <span className="flex items-center gap-1 text-[10px]"><span className="h-2 w-2 rounded-full bg-accent-green" /><span className="text-text-muted">{completedCount}</span></span>}
          </div>
        )}
      </div>
      {agents.size === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-bg-tertiary">
            <svg className="h-7 w-7 text-text-muted/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="18" r="3" /><path d="M12 9v3" /><path d="M9 15l-3 3" /><path d="M15 15l3 3" /></svg>
          </div>
          <p className="text-sm font-medium text-text-muted">No agents yet</p>
          <p className="text-center text-xs text-text-muted/60">Start a research query to see the agent pipeline</p>
        </div>
      ) : (
        <div className="flex-1">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={onNodeClick} onEdgeClick={onEdgeClick} fitView fitViewOptions={{ padding: 0.15 }} className="bg-bg-primary" proOptions={{ hideAttribution: true }}>
            <Background color="#27272a" gap={24} size={1} />
            <Controls className="!bg-bg-secondary !border-border-subtle !rounded-lg !shadow-lg" showInteractive={false} />
            <MiniMap className="!bg-bg-secondary !border-border-subtle !rounded-lg" nodeColor={(n) => getStatusColor((n.data?.status as AgentStatus) || "idle").bg} maskColor="rgba(0,0,0,0.6)" style={{ borderRadius: 8 }} />
          </ReactFlow>
        </div>
      )}
    </div>
  )
}
