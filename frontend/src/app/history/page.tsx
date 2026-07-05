"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Clock, FileSearch, Trash2, ChevronRight, BarChart3, CheckCircle, Globe } from "lucide-react"
import { useHistoryStore, type ResearchEntry } from "@/src/store/history"
import { Button } from "@/src/components/ui/button"

export default function HistoryPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const { entries, deleteEntry, clearHistory } = useHistoryStore()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login")
    }
  }, [status, router])

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <div className="h-3 w-3 rounded-full bg-accent-blue animate-pulse" />
      </div>
    )
  }

  if (!session) return null

  const formatDate = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const truncate = (text: string, max: number) =>
    text.length > max ? text.slice(0, max) + "..." : text

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border-subtle bg-bg-secondary">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <Link href="/dashboard" className="text-text-muted hover:text-text-primary transition-colors">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-sm font-semibold text-text-primary">Research History</h1>
            <span className="rounded-full bg-bg-tertiary px-2 py-0.5 text-xs text-text-muted">
              {entries.length} {entries.length === 1 ? "session" : "sessions"}
            </span>
          </div>
          {entries.length > 0 && (
            <Button variant="ghost" size="sm" onClick={clearHistory} className="text-xs text-text-muted hover:text-accent-red">
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              Clear All
            </Button>
          )}
        </div>
      </header>

      {/* Content */}
      <div className="mx-auto max-w-5xl px-6 py-8">
        {entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <FileSearch className="h-12 w-12 text-text-muted mb-4" />
            <h2 className="text-lg font-semibold text-text-primary">No research history yet</h2>
            <p className="mt-2 text-sm text-text-muted">
              Complete a research session to see it here.
            </p>
            <Button size="sm" className="mt-6" onClick={() => window.location.href = "/dashboard"}>
              Start Research
              <ChevronRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="rounded-xl border border-border-subtle bg-bg-secondary overflow-hidden transition-colors hover:border-border-strong"
              >
                {/* Summary row */}
                <div
                  className="flex items-center gap-4 p-4 cursor-pointer"
                  onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-text-primary truncate">
                      {entry.query}
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-xs text-text-muted">
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatDate(entry.createdAt)}
                      </span>
                      <span className="flex items-center gap-1">
                        <BarChart3 className="h-3 w-3" />
                        {entry.agentCount} agents
                      </span>
                      <span className="flex items-center gap-1">
                        <CheckCircle className="h-3 w-3 text-accent-green" />
                        {entry.verifiedClaimsCount} verified
                      </span>
                      <span className="flex items-center gap-1">
                        <Globe className="h-3 w-3 text-accent-blue" />
                        {entry.sourcesCount} sources
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-text-muted">{entry.durationS.toFixed(0)}s</span>
                    <ChevronRight
                      className={`h-4 w-4 text-text-muted transition-transform ${
                        expandedId === entry.id ? "rotate-90" : ""
                      }`}
                    />
                  </div>
                </div>

                {/* Expanded details */}
                {expandedId === entry.id && (
                  <div className="border-t border-border-subtle p-4 space-y-4">
                    {/* Tool calls */}
                    {Object.keys(entry.toolCalls).length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
                          Tool Calls
                        </h4>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(entry.toolCalls).map(([tool, count]) => (
                            <div
                              key={tool}
                              className="flex items-center gap-1.5 rounded-lg bg-bg-tertiary px-2.5 py-1"
                            >
                              <span className="text-xs font-medium text-text-primary">{tool}</span>
                              <span className="rounded-full bg-accent-blue/20 px-1.5 py-0.5 text-[10px] font-medium text-accent-blue">
                                {count}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Report preview */}
                    {entry.report && (
                      <div>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
                          Report Preview
                        </h4>
                        <div className="rounded-lg bg-bg-tertiary p-3 text-xs text-text-secondary max-h-40 overflow-y-auto">
                          {truncate(entry.report, 500)}
                        </div>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex items-center gap-2 pt-2">
                      <Button variant="outline" size="sm" className="text-xs" onClick={() => window.location.href = `/history/${entry.id}`}>
                        View Full Report
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs text-text-muted hover:text-accent-red"
                        onClick={() => deleteEntry(entry.id)}
                      >
                        <Trash2 className="h-3 w-3 mr-1" />
                        Delete
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
