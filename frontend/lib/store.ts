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
  apiCalls: 0,
  agentsActive: 0,
  estimatedRemainingS: 0,
  totalTokens: 0,
  totalCalls: 0,
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
      return { agents: updated }
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
      return { agents: updated }
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
      case "agent_status": {
        // Backend emits { agent, status, agent_count } — no model/tier/question
        const data = event.data as {
          agent: string
          status: AgentStatus
          agent_count?: number
        }
        state.upsertAgent(data.agent, {
          status: data.status,
          // Derive a human-readable model label from the agent id since the
          // backend doesn't attach per-worker model info to this event yet.
          model: data.agent,
        })
        break
      }
      case "tool_call": {
        const data = event.data as {
          agent_id: string
          tool_name: string
          latency_ms: number
        }
        const agent = state.agents.get(data.agent_id)
        if (agent) {
          const updated = new Map(state.agents)
          updated.set(data.agent_id, {
            ...agent,
            toolCalls: [
              ...(agent.toolCalls || []),
              {
                toolName: data.tool_name,
                inputSummary: "",
                outputSummary: "",
                latencyMs: data.latency_ms,
                timestamp: Date.now(),
              },
            ],
          })
          set({ agents: updated })
        }
        break
      }
      case "cost_update": {
        // Backend emits snake_case; map to the camelCase CostStats shape.
        const data = event.data as {
          total_cost?: number
          api_calls?: number
          agents_active?: number
          estimated_remaining_s?: number
          total_tokens?: number
          total_calls?: number
        }
        state.updateCostStats({
          totalCost: data.total_cost ?? 0,
          apiCalls: data.api_calls ?? 0,
          agentsActive: data.agents_active ?? 0,
          estimatedRemainingS: data.estimated_remaining_s ?? 0,
          totalTokens: data.total_tokens ?? 0,
          totalCalls: data.total_calls ?? 0,
        })
        break
      }
      case "claim_verified": {
        const data = event.data as {
          claim: string
          trust_score: number
          trust_label: string
        }
        state.addCitationNode({
          id: `claim-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          label: data.claim.slice(0, 60),
          type: "Claim",
          trustScore: data.trust_score,
          trustLabel: data.trust_label as "HIGH" | "MODERATE" | "LOW",
        })
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
