import { create } from "zustand"
import type {
  AgentNode,
  AgentStatus,
  CitationNode,
  CitationEdge,
  CostStats,
  TimingEntry,
  SSEEvent,
} from "./types"

interface ResearchState {
  sessionId: string | null
  query: string
  status: string
  isStreaming: boolean
  finalReport: string | null
  agents: Map<string, AgentNode>
  agentEdges: Array<{ source: string; target: string }>
  citationNodes: CitationNode[]
  citationEdges: CitationEdge[]
  costStats: CostStats
  timing: TimingEntry[]
  selectedAgentId: string | null

  setSession: (id: string, query: string) => void
  setStatus: (status: string) => void
  setStreaming: (v: boolean) => void
  setFinalReport: (report: string | null) => void
  upsertAgent: (id: string, patch: Partial<AgentNode>) => void
  setAgentStatus: (id: string, status: AgentStatus) => void
  addAgentEdge: (source: string, target: string) => void
  addCitationNode: (node: CitationNode) => void
  addCitationEdge: (edge: CitationEdge) => void
  updateCostStats: (stats: Partial<CostStats>) => void
  addTiming: (entry: TimingEntry) => void
  selectAgent: (id: string | null) => void
  processSSEEvent: (event: SSEEvent) => void
  reset: () => void
}

const initialCostStats: CostStats = {
  totalCost: 0,
  agentsActive: 0,
  estimatedRemainingS: 0,
  totalTokens: 0,
  totalCalls: 0,
  totalInputTokens: 0,
  totalOutputTokens: 0,
  elapsedS: 0,
  toolCalls: 0,
}

export const useResearchStore = create<ResearchState>((set, get) => ({
  sessionId: null,
  query: "",
  status: "idle",
  isStreaming: false,
  agents: new Map(),
  agentEdges: [],
  citationNodes: [],
  citationEdges: [],
  costStats: { ...initialCostStats },
  timing: [],
  selectedAgentId: null,
  finalReport: null,

  setSession: (id, query) => set({ sessionId: id, query, status: "started" }),
  setStatus: (status) => set({ status }),
  setStreaming: (v) => set({ isStreaming: v }),
  setFinalReport: (report) => set({ finalReport: report }),

  upsertAgent: (id, patch) =>
    set((state) => {
      const existing = state.agents.get(id) || {
        id,
        label: id,
        status: "idle" as const,
        model: "",
        tier: "fast" as const,
      }
      const updated = new Map(state.agents)
      updated.set(id, { ...existing, ...patch })
      const activeCount = Math.max(state.costStats.agentsActive, updated.size)
      return {
        agents: updated,
        costStats: { ...state.costStats, agentsActive: activeCount },
      }
    }),

  setAgentStatus: (id, status) =>
    set((state) => {
      const agent = state.agents.get(id)
      if (!agent) return state
      const updated = new Map(state.agents)
      updated.set(id, {
        ...agent,
        status,
        ...(status === "running" ? { startTime: Date.now() } : {}),
        ...(status === "completed" || status === "failed"
          ? { endTime: Date.now() }
          : {}),
      })
      const activeCount = Math.max(state.costStats.agentsActive, updated.size)
      return {
        agents: updated,
        costStats: { ...state.costStats, agentsActive: activeCount },
      }
    }),

  addAgentEdge: (source, target) =>
    set((state) => ({
      agentEdges: [...state.agentEdges, { source, target }],
    })),

  addCitationNode: (node) =>
    set((state) => {
      const exists = state.citationNodes.find((n) => n.id === node.id)
      if (exists) return state
      return { citationNodes: [...state.citationNodes, node] }
    }),

  addCitationEdge: (edge) =>
    set((state) => ({
      citationEdges: [...state.citationEdges, edge],
    })),

  updateCostStats: (stats) =>
    set((state) => ({
      costStats: { ...state.costStats, ...stats },
    })),

  addTiming: (entry) =>
    set((state) => ({ timing: [...state.timing, entry] })),

  selectAgent: (id) => set({ selectedAgentId: id }),

  processSSEEvent: (event) => {
    const state = get()
    switch (event.event) {
      // agent_start: emitted when ANY graph node begins (planner, orchestrator, critic, etc.)
      case "agent_start": {
        const data = event.data as { agent: string; message?: string; model?: string; tier?: string }
        if (!data.agent || data.agent === "system") break
        const existing = state.agents.get(data.agent)
        if (existing && existing.status === "completed") break
        const updated = new Map(state.agents)
        updated.set(data.agent, {
          id: data.agent,
          label: data.agent,
          status: "running",
          model: data.model || existing?.model || data.agent,
          tier: (data.tier as "reasoning" | "fast") || existing?.tier || "fast",
          startTime: existing?.startTime || Date.now(),
          toolCalls: existing?.toolCalls || [],
          llmCalls: existing?.llmCalls || 0,
        })
        const activeCount = Math.max(state.costStats.agentsActive, updated.size)
        set({
          agents: updated,
          costStats: { ...state.costStats, agentsActive: activeCount },
        })
        break
      }
      // agent_complete: emitted when a graph node finishes
      case "agent_complete": {
        const data = event.data as { agent: string; status: AgentStatus; agent_count?: number; duration?: string }
        if (!data.agent) break
        const agentName = data.agent
        const updated = new Map(state.agents)
        // Only update the compound node itself (e.g. "searchers"), NOT individual
        // workers (searcher-0, etc.) — those are handled by per-worker agent_status
        // events so they keep their question/tool/duration detail.
        const existing = updated.get(agentName)
        if (existing) {
          const elapsed = data.duration || (existing.startTime
            ? `${((Date.now() - existing.startTime) / 1000).toFixed(1)}s`
            : "—")
          updated.set(agentName, {
            ...existing,
            status: (data.status as AgentStatus) || "completed",
            endTime: Date.now(),
            duration: elapsed,
          })
        } else {
          updated.set(agentName, {
            id: agentName,
            label: agentName,
            status: (data.status as AgentStatus) || "completed",
            model: agentName,
            tier: "fast",
            startTime: Date.now(),
            endTime: Date.now(),
            duration: data.duration || "0s",
          })
        }
        const activeCount = Math.max(state.costStats.agentsActive, updated.size)
        set({
          agents: updated,
          costStats: { ...state.costStats, agentsActive: activeCount },
        })
        break
      }
      // agent_status: emitted for individual worker nodes (agent_id, e.g.
      // searcher-0) AND compound nodes (agent, e.g. searchers). Workers carry
      // the per-worker question; compound nodes carry the aggregate status.
      case "agent_status": {
        const data = event.data as {
          agent?: string
          agent_id?: string
          status: AgentStatus
          model?: string
          tier?: string
          question?: string
          url?: string
          claim?: string
        }
        const agentId = data.agent_id ?? data.agent
        if (!agentId || agentId === "system") break
        const existing = state.agents.get(agentId)
        const updated = new Map(state.agents)
        const isTerminal = data.status === "completed" || data.status === "failed"
        const startTime = existing?.startTime
        updated.set(agentId, {
          id: agentId,
          label: agentId,
          status: data.status,
          model: data.model || existing?.model || agentId,
          tier: (data.tier as "reasoning" | "fast") || existing?.tier || "fast",
          question: data.question ?? data.url ?? (data.claim as string | undefined),
          startTime:
            startTime || (data.status === "running" ? Date.now() : undefined),
          endTime: isTerminal ? existing?.endTime || Date.now() : existing?.endTime,
          duration:
            isTerminal && startTime
              ? `${(
                  ((existing?.endTime || Date.now()) -
                    startTime) /
                  1000
                ).toFixed(1)}s`
              : existing?.duration,
          toolCalls: existing?.toolCalls || [],
          llmCalls: existing?.llmCalls || (isTerminal ? 1 : 0),
        })
        const activeCount = Math.max(state.costStats.agentsActive, updated.size)
        set({
          agents: updated,
          costStats: { ...state.costStats, agentsActive: activeCount },
        })
        break
      }
      // tool_call: each successful tool invocation by a worker
      case "tool_call": {
        const data = event.data as { agent_id: string; tool_name: string; latency_ms: number }
        const existing = state.agents.get(data.agent_id)
        // Always ensure the agent node exists (create if missing)
        const base = existing || { id: data.agent_id, label: data.agent_id, status: "running" as const, model: "", tier: "fast" as const }
        const updated = new Map(state.agents)
        updated.set(data.agent_id, {
          ...base,
          status: base.status === "idle" ? "running" : base.status,
          startTime: base.startTime || Date.now(),
          toolCalls: [...(base.toolCalls || []), {
            toolName: data.tool_name,
            inputSummary: "",
            outputSummary: "",
            latencyMs: data.latency_ms,
            timestamp: Date.now(),
          }],
        })
        const activeCount = Math.max(state.costStats.agentsActive, updated.size)
        set({
          agents: updated,
          costStats: { ...state.costStats, agentsActive: activeCount },
        })
        break
      }
      case "cost_update": {
        // Backend emits snake_case; map to the camelCase CostStats shape.
        const data = event.data as {
          total_cost?: number
          llm_calls?: number
          agents_active?: number
          tool_calls?: number
          estimated_remaining_s?: number
          total_tokens?: number
          total_input_tokens?: number
          total_output_tokens?: number
          elapsed_s?: number
        }
        // Track PEAK agents spawned (the value may drop back toward zero in
        // late pipeline stages as workers finish, but we want to show how many
        // were spawned across the whole run).
        const currentActive = data.agents_active ?? 0
        const prevPeak = state.costStats.agentsActive ?? 0
        const peakActive = Math.max(prevPeak, currentActive)
        state.updateCostStats({
          totalCost: data.total_cost ?? 0,
          totalCalls: data.llm_calls ?? 0,
          agentsActive: peakActive,
          toolCalls: data.tool_calls ?? 0,
          estimatedRemainingS: data.estimated_remaining_s ?? 0,
          totalTokens: data.total_tokens ?? (data.total_input_tokens ?? 0) + (data.total_output_tokens ?? 0),
          totalInputTokens: data.total_input_tokens ?? 0,
          totalOutputTokens: data.total_output_tokens ?? 0,
          elapsedS: data.elapsed_s ?? 0,
        })
        break
      }
      case "claim_verified": {
        const data = event.data as {
          claim: string
          trust_score: number
          trust_label: string
          sources?: Array<{ url: string; title: string; snippet: string; tool_name: string }>
        }
        const claimId = `claim-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
        // Add the claim node.
        state.addCitationNode({
          id: claimId,
          label: data.claim.slice(0, 60),
          type: "Claim",
          trustScore: data.trust_score,
          trustLabel: data.trust_label as "HIGH" | "MODERATE" | "LOW",
        })
        // Add a Source node per cited source + a SUPPORTS edge claim→source.
        // Source nodes are keyed by url so the same URL shared across claims
        // reuses one node (and naturally draws multiple incoming edges).
        for (const src of data.sources || []) {
          if (!src.url) continue
          const sourceId = `src-${src.url}`
          state.addCitationNode({
            id: sourceId,
            label: src.title || src.url,
            type: "Source",
            url: src.url,
            title: src.title,
            snippet: src.snippet,
            toolName: src.tool_name,
          } as CitationNode)
          state.addCitationEdge({ source: claimId, target: sourceId, type: "SUPPORTS" })
        }
        break
      }
      case "done": {
        const data = event.data as {
          final_report?: string | null
          agent_count?: number
          verified_claims_count?: number
          sources_count?: number
        }
        state.setStatus("done")
        state.setStreaming(false)
        if (data.final_report) {
          state.setFinalReport(data.final_report)
        }
        break
      }
      case "error":
        state.setStatus("failed")
        state.setStreaming(false)
        break
    }
  },

  reset: () =>
    set({
      sessionId: null,
      query: "",
      status: "idle",
      isStreaming: false,
      finalReport: null,
      agents: new Map(),
      agentEdges: [],
      citationNodes: [],
      citationEdges: [],
      costStats: { ...initialCostStats },
      timing: [],
      selectedAgentId: null,
    }),
}))
