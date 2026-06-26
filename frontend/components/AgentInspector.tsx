"use client"

import { useResearchStore } from "@/lib/store"
import { X, Clock, Cpu, Activity } from "lucide-react"
import { StatusDot } from "./TrustBadge"

export function AgentInspector() {
  const selectedAgentId = useResearchStore((s) => s.selectedAgentId)
  const agents = useResearchStore((s) => s.agents)
  const selectAgent = useResearchStore((s) => s.selectAgent)

  const agent = selectedAgentId ? agents.get(selectedAgentId) : null

  if (!agent) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-muted">
        Click an agent node to inspect its activity
      </div>
    )
  }

  const duration =
    agent.startTime && agent.endTime
      ? ((agent.endTime - agent.startTime) / 1000).toFixed(1) + "s"
      : agent.startTime
      ? `${((Date.now() - agent.startTime) / 1000).toFixed(1)}s elapsed`
      : "—"

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2">
        <div className="flex items-center gap-2">
          <StatusDot status={agent.status} />
          <span className="text-sm font-medium text-text-primary">
            {agent.id}
          </span>
          <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-xs text-text-muted">
            {agent.tier}
          </span>
        </div>
        <button
          onClick={() => selectAgent(null)}
          className="rounded p-1 text-text-muted hover:bg-bg-hover hover:text-text-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Stats */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-lg bg-bg-tertiary p-3">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <Clock className="h-3 w-3" />
              Duration
            </div>
            <div className="mt-1 text-sm font-medium text-text-primary">
              {duration}
            </div>
          </div>
          <div className="rounded-lg bg-bg-tertiary p-3">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <Cpu className="h-3 w-3" />
              Model
            </div>
            <div className="mt-1 truncate text-sm font-medium text-text-primary">
              {agent.model}
            </div>
          </div>
          <div className="rounded-lg bg-bg-tertiary p-3">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <Activity className="h-3 w-3" />
              Tool Calls
            </div>
            <div className="mt-1 text-sm font-medium text-text-primary">
              {agent.toolCalls?.length || 0}
            </div>
          </div>
        </div>

        {/* Question (if searcher) */}
        {agent.question && (
          <div>
            <h4 className="mb-1 text-xs font-medium uppercase tracking-wider text-text-muted">
              Sub-Question
            </h4>
            <p className="rounded-lg bg-bg-tertiary p-3 text-sm text-text-secondary">
              {agent.question}
            </p>
          </div>
        )}

        {/* Question (duplicate check) */}
        {!agent.question && agent.toolCalls && agent.toolCalls.length === 0 && (
          <div className="rounded-lg border border-border-subtle bg-bg-tertiary p-3 text-xs text-text-muted">
            Awaiting tool dispatch...
          </div>
        )}

        {/* Tool Calls */}
        {agent.toolCalls && agent.toolCalls.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-text-muted">
              Tool Calls
            </h4>
            <div className="space-y-2">
              {agent.toolCalls.map((tc, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-border-subtle bg-bg-tertiary p-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-accent-blue">
                      {tc.toolName}
                    </span>
                    <span className="text-xs text-text-muted">
                      {tc.latencyMs.toFixed(0)}ms
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
