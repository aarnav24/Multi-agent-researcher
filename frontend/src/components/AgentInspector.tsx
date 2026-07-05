"use client"

import { useEffect, useState } from "react"
import { useResearchStore } from "@/src/lib/store"
import { X, Clock, Cpu, Activity, Zap, CheckCircle, XCircle, Loader2, ChevronRight } from "lucide-react"
import { StatusDot } from "./TrustBadge"
import type { AgentStatus } from "@/src/lib/types"

export function AgentInspector() {
  const selectedAgentId = useResearchStore((s) => s.selectedAgentId)
  const agents = useResearchStore((s) => s.agents)
  const selectAgent = useResearchStore((s) => s.selectAgent)
  const [, setTick] = useState(0)

  // Force re-render every 2s to update live duration for running agents
  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 2000)
    return () => clearInterval(interval)
  }, [])

  const agent = selectedAgentId ? agents.get(selectedAgentId) : null

  if (!agent) {
    return (
      <div className="flex h-full flex-col">
        <PanelHeader title="Inspector" subtitle="Agent details" />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-bg-tertiary">
            <Cpu className="h-6 w-6 text-text-muted/40" />
          </div>
          <p className="text-sm font-medium text-text-muted">No agent selected</p>
          <p className="text-center text-xs text-text-muted/60">
            Click on any agent in the tree above to inspect its activity
          </p>
        </div>
      </div>
    )
  }

  // Use pre-calculated duration if available, otherwise compute live
  const duration = agent.duration
    || (agent.startTime && agent.endTime
      ? ((agent.endTime - agent.startTime) / 1000).toFixed(1) + "s"
      : agent.startTime
      ? `${((Date.now() - agent.startTime) / 1000).toFixed(1)}s elapsed`
      : "—")

  const isRunning = agent.status === "running"
  const isCompleted = agent.status === "completed"
  const isFailed = agent.status === "failed"
  const statusColor = isRunning ? "#eab308" : isCompleted ? "#22c55e" : isFailed ? "#ef4444" : "#71717a"

  const toolCallCount = agent.toolCalls?.length || 0
  const llmCalls = agent.llmCalls || (agent.status !== "idle" && agent.status !== "running" ? 1 : 0)

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-lg"
            style={{ backgroundColor: `${statusColor}15` }}
          >
            <Cpu className="h-3.5 w-3.5" style={{ color: statusColor }} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-text-primary">{agent.id}</span>
              <span
                className="rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                style={{
                  backgroundColor: agent.tier === "reasoning" ? "#a855f720" : "#3b82f620",
                  color: agent.tier === "reasoning" ? "#c084fc" : "#60a5fa",
                }}
              >
                {agent.tier}
              </span>
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <StatusDot status={agent.status} />
              <span className="text-[10px] font-medium capitalize" style={{ color: statusColor }}>
                {agent.status}
              </span>
            </div>
          </div>
        </div>
        <button
          onClick={() => selectAgent(null)}
          className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Stats Grid */}
        <div className="grid grid-cols-4 gap-2">
          <StatCard
            icon={<Clock className="h-3.5 w-3.5" />}
            label="Duration"
            shortLabel="TIME"
            value={duration}
            color="#3b82f6"
          />
          <StatCard
            icon={<Zap className="h-3.5 w-3.5" />}
            label="LLM Calls"
            shortLabel="LLM"
            value={llmCalls.toString()}
            color="#a855f7"
          />
          <StatCard
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Tools"
            shortLabel="TLS"
            value={toolCallCount.toString()}
            color="#22c55e"
          />
          <StatCard
            icon={<Cpu className="h-3.5 w-3.5" />}
            label="Model"
            shortLabel="MDL"
            value={(agent.model.split("/").pop() || agent.model).slice(0, 8)}
            color="#f97316"
          />
        </div>

        {/* Sub-Question */}
        {agent.question && (
          <div className="rounded-xl border border-border-subtle bg-bg-tertiary/50 p-3">
            <h4 className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted">
              <ChevronRight className="h-3 w-3" />
              Sub-Question
            </h4>
            <p className="text-xs leading-relaxed text-text-secondary">{agent.question}</p>
          </div>
        )}

        {/* Waiting state — only show for RUNNING workers with no tools yet.
            Completed/failed workers always have tools (or a terminal status), so this
            naturally disappears when the worker finishes. */}
        {isRunning && !agent.question && toolCallCount === 0 && agent.id.match(/(searcher|browser|fact_checker)/) && (
          <div className="flex items-center gap-3 rounded-xl border border-border-subtle bg-bg-tertiary/50 p-3">
            <Loader2 className="h-4 w-4 animate-spin text-accent-yellow" />
            <span className="text-xs text-text-muted">Awaiting tool dispatch...</span>
          </div>
        )}

        {/* Tool Calls Timeline */}
        {agent.toolCalls && agent.toolCalls.length > 0 && (
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted">
              <Activity className="h-3 w-3" />
              Tool Calls ({toolCallCount})
            </h4>
            <div className="space-y-1.5">
              {agent.toolCalls.map((tc, i) => {
                const maxLatency = Math.max(...agent.toolCalls!.map((t) => t.latencyMs), 1)
                const barWidth = (tc.latencyMs / maxLatency) * 100
                return (
                  <div
                    key={i}
                    className="group rounded-lg border border-border-subtle bg-bg-tertiary/50 p-2 transition-colors hover:bg-bg-tertiary"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div
                          className="flex h-5 w-5 items-center justify-center rounded-md text-[10px] font-bold text-white"
                          style={{ backgroundColor: getToolColor(tc.toolName) }}
                        >
                          {tc.toolName.slice(0, 2).toUpperCase()}
                        </div>
                        <span className="text-xs font-medium text-text-primary">{tc.toolName}</span>
                      </div>
                      <span className="text-[10px] font-mono text-text-muted">
                        {tc.latencyMs.toFixed(0)}ms
                      </span>
                    </div>
                    {/* Latency bar */}
                    <div className="mt-1.5 h-1 w-full rounded-full bg-bg-tertiary overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-300"
                        style={{
                          width: `${barWidth}%`,
                          backgroundColor: getToolColor(tc.toolName),
                          opacity: 0.7,
                        }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PanelHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-text-muted">{title}</h3>
        {subtitle && <span className="text-[10px] text-text-muted/60">{subtitle}</span>}
      </div>
    </div>
  )
}

function StatCard({
  icon,
  label,
  shortLabel,
  value,
  color,
}: {
  icon: React.ReactNode
  label: string
  shortLabel?: string
  value: string
  color: string
}) {
  return (
    <div className="rounded-xl border border-border-subtle bg-bg-tertiary/50 p-2.5 transition-colors hover:bg-bg-tertiary">
      <div className="flex items-center gap-1.5" style={{ color }}>
        {icon}
        <span className="text-[10px] font-medium uppercase tracking-wider">{shortLabel || label}</span>
      </div>
      <div className="mt-1 truncate text-sm font-semibold text-text-primary">{value}</div>
      <div className="text-[10px] text-text-muted/60">{label}</div>
    </div>
  )
}

function getToolColor(toolName: string): string {
  const colors: Record<string, string> = {
    arxiv: "#ef4444",
    exa: "#3b82f6",
    serper: "#22c55e",
    tavily: "#eab308",
    github: "#a855f7",
    ddg: "#f97316",
    browser: "#06b6d4",
    pgvector: "#ec4899",
  }
  return colors[toolName] || "#71717a"
}
