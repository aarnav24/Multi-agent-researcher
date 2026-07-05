"use client"

import { useResearchStore } from "@/src/lib/store"
import { Activity, Clock, Zap, CheckCircle, ShieldCheck } from "lucide-react"

export function CostTicker() {
  const costStats = useResearchStore((s) => s.costStats)
  const query = useResearchStore((s) => s.query)
  const isStreaming = useResearchStore((s) => s.isStreaming)
  const citationNodes = useResearchStore((s) => s.citationNodes)

  // Trust breakdown of verified claims (real Claim nodes in the citation store).
  const claims = citationNodes.filter((n) => n.type === "Claim")
  const highCount = claims.filter((c) => (c.trustScore ?? 0) >= 81).length
  const modCount = claims.filter((c) => (c.trustScore ?? 0) >= 51 && (c.trustScore ?? 0) <= 80).length
  const lowCount = claims.filter((c) => (c.trustScore ?? 0) <= 50).length
  const avgTrust = claims.length
    ? Math.round(claims.reduce((sum, c) => sum + (c.trustScore ?? 0), 0) / claims.length)
    : 0

  return (
    <div className="p-4">
      {/* Query Display */}
      <div className="mb-4">
        <div className="mb-1 text-xs font-medium uppercase tracking-wider text-text-muted">
          Research Query
        </div>
        <p className="line-clamp-2 text-sm text-text-secondary">{query}</p>
      </div>

      {/* Stats Grid: 2x2 with 4 key metrics */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          icon={<Activity className="h-4 w-4 text-accent-blue" />}
          label="Agents Spawned"
          value={costStats.agentsActive.toString()}
          sub="workers created"
        />
        <StatCard
          icon={<Zap className="h-4 w-4 text-accent-purple" />}
          label="LLM Calls"
          value={costStats.totalCalls.toString()}
          sub="successful only"
        />
        <StatCard
          icon={<CheckCircle className="h-4 w-4 text-accent-green" />}
          label="Tool Calls"
          value={costStats.toolCalls.toString()}
          sub="arxiv, exa, serper..."
        />
        <StatCard
          icon={<Clock className="h-4 w-4 text-accent-yellow" />}
          label="ETA"
          value={formatETA(costStats.estimatedRemainingS)}
          sub={formatNumber(costStats.totalTokens) + " tokens | " + Math.round(costStats.elapsedS || 0) + "s elapsed"}
        />
      </div>

      {/* Trust Score Overview — the core verification metric */}
      {claims.length > 0 && (
        <div className="mt-4 rounded-lg bg-bg-tertiary p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <ShieldCheck className="h-3.5 w-3.5" />
              Claim Trust
            </div>
            <span className="text-xs font-mono text-text-muted">avg {avgTrust}/100</span>
          </div>
          {/* Stacked bar showing trust distribution */}
          <div className="h-2 w-full overflow-hidden rounded-full bg-bg-primary flex">
            {highCount > 0 && (
              <div className="h-full bg-accent-green" style={{ width: `${(highCount / claims.length) * 100}%` }} />
            )}
            {modCount > 0 && (
              <div className="h-full bg-accent-yellow" style={{ width: `${(modCount / claims.length) * 100}%` }} />
            )}
            {lowCount > 0 && (
              <div className="h-full bg-accent-red" style={{ width: `${(lowCount / claims.length) * 100}%` }} />
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px]">
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-accent-green" />{highCount} high</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-accent-yellow" />{modCount} mod</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-accent-red" />{lowCount} low</span>
            <span className="text-text-muted">{claims.length} claims</span>
          </div>
        </div>
      )}

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
