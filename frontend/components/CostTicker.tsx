"use client"

import { useResearchStore } from "@/lib/store"
import { Activity, Clock, Zap, CheckCircle } from "lucide-react"

export function CostTicker() {
  const costStats = useResearchStore((s) => s.costStats)
  const query = useResearchStore((s) => s.query)
  const isStreaming = useResearchStore((s) => s.isStreaming)

  return (
    <div className="p-4">
      {/* Query Display */}
      <div className="mb-4">
        <div className="mb-1 text-xs font-medium uppercase tracking-wider text-text-muted">
          Research Query
        </div>
        <p className="line-clamp-2 text-sm text-text-secondary">{query}</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          icon={<Activity className="h-4 w-4 text-accent-blue" />}
          label="API Calls"
          value={costStats.apiCalls.toString()}
          sub="tool invocations"
        />
        <StatCard
          icon={<Zap className="h-4 w-4 text-accent-purple" />}
          label="Tokens"
          value={formatNumber(costStats.totalTokens)}
          sub={`${costStats.totalCalls} LLM calls`}
        />
        <StatCard
          icon={<Clock className="h-4 w-4 text-accent-yellow" />}
          label="ETA"
          value={formatETA(costStats.estimatedRemainingS)}
          sub="remaining"
        />
        <StatCard
          icon={<CheckCircle className="h-4 w-4 text-accent-green" />}
          label="Cost"
          value="$0.00"
          sub="all free tools"
        />
      </div>

      {/* Live indicator */}
      <div className="mt-4 flex items-center gap-2 rounded-lg bg-bg-tertiary px-3 py-2">
        <div
          className={`h-2 w-2 rounded-full ${
            isStreaming ? "animate-pulse bg-accent-green" : "bg-text-muted"
          }`}
        />
        <span className="text-xs text-text-muted">
          {isStreaming
            ? "Live updates streaming via SSE"
            : "Waiting for research to start"}
        </span>
      </div>
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode
  label: string
  value: string
  sub: string
}) {
  return (
    <div className="rounded-lg bg-bg-tertiary p-3">
      <div className="flex items-center gap-1.5 text-xs text-text-muted">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold text-text-primary">{value}</div>
      <div className="text-xs text-text-muted">{sub}</div>
    </div>
  )
}

function formatETA(seconds: number): string {
  if (seconds <= 0) return "—"
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toString()
}
