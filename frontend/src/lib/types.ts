export type AgentStatus = "idle" | "running" | "completed" | "failed"

export interface AgentNode {
  id: string
  label: string
  status: AgentStatus
  model: string
  tier: "reasoning" | "fast"
  question?: string
  startTime?: number
  endTime?: number
  duration?: string
  toolCalls?: ToolCall[]
  llmCalls?: number
}

export interface ToolCall {
  toolName: string
  inputSummary: string
  outputSummary: string
  latencyMs: number
  timestamp: number
}

export interface CitationNode {
  id: string
  label: string
  type: "Claim" | "Source" | "SubQuestion"
  trustScore?: number
  trustLabel?: "HIGH" | "MODERATE" | "LOW"
  url?: string
  title?: string
  snippet?: string
  toolName?: string
}

export interface CitationEdge {
  source: string
  target: string
  type: "SUPPORTS" | "CONTRADICTS" | "ANSWERS" | "RELATED"
}

export interface CostStats {
  totalCost: number
  agentsActive: number
  estimatedRemainingS: number
  totalTokens: number
  totalCalls: number
  totalInputTokens: number
  totalOutputTokens: number
  elapsedS: number
  toolCalls: number
}

export interface TimingEntry {
  tier: string
  agent: string
  model: string
  latencyS: number
  inputTokens: number
  outputTokens: number
}

export type SSEEventType =
  | "agent_start"
  | "agent_complete"
  | "agent_status"
  | "tool_call"
  | "finding"
  | "claim_verified"
  | "citation_update"
  | "cost_update"
  | "timing_summary"
  | "done"
  | "error"

export interface SSEEvent {
  event: SSEEventType
  data: Record<string, unknown>
}
