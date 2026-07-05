"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter, useParams } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Clock, BarChart3, CheckCircle, Globe, Trash2 } from "lucide-react"
import { useHistoryStore, type ResearchEntry } from "@/src/store/history"
import { ReportView } from "@/src/components/ReportView"
import { Button } from "@/src/components/ui/button"

export default function HistoryDetailPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const params = useParams()
  const id = params?.id as string
  const { getEntry, deleteEntry } = useHistoryStore()
  const [entry, setEntry] = useState<ResearchEntry | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login")
    }
  }, [status, router])

  useEffect(() => {
    if (id) {
      const found = getEntry(id)
      setEntry(found || null)
      setLoading(false)
    }
  }, [id, getEntry])

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <div className="h-3 w-3 rounded-full bg-accent-blue animate-pulse" />
      </div>
    )
  }

  if (!session) return null

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <div className="h-3 w-3 rounded-full bg-accent-blue animate-pulse" />
      </div>
    )
  }

  if (!entry) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-bg-primary">
        <h2 className="text-lg font-semibold text-text-primary">Report not found</h2>
        <p className="text-sm text-text-muted">This research session may have been deleted.</p>
        <Button size="sm" onClick={() => router.push("/history")}>
          <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
          Back to History
        </Button>
      </div>
    )
  }

  const formatDate = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const handleDelete = () => {
    deleteEntry(entry.id)
    router.push("/history")
  }

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border-subtle bg-bg-secondary">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <Link href="/history" className="text-text-muted hover:text-text-primary transition-colors">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-sm font-semibold text-text-primary truncate max-w-[400px]">
              {entry.query}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="text-xs text-text-muted hover:text-accent-red" onClick={handleDelete}>
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              Delete
            </Button>
          </div>
        </div>
      </header>

      {/* Meta stats */}
      <div className="mx-auto max-w-5xl px-6 py-4">
        <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formatDate(entry.createdAt)}
          </span>
          <span className="flex items-center gap-1">
            <BarChart3 className="h-3 w-3" />
            {entry.agentCount} agents spawned
          </span>
          <span className="flex items-center gap-1">
            <CheckCircle className="h-3 w-3 text-accent-green" />
            {entry.verifiedClaimsCount} verified claims
          </span>
          <span className="flex items-center gap-1">
            <Globe className="h-3 w-3 text-accent-blue" />
            {entry.sourcesCount} sources
          </span>
          <span>{entry.durationS.toFixed(0)}s duration</span>
        </div>

        {/* Tool calls */}
        {Object.keys(entry.toolCalls).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(entry.toolCalls).map(([tool, count]) => (
              <div key={tool} className="flex items-center gap-1.5 rounded-lg bg-bg-tertiary px-2.5 py-1">
                <span className="text-xs font-medium text-text-primary">{tool}</span>
                <span className="rounded-full bg-accent-blue/20 px-1.5 py-0.5 text-[10px] font-medium text-accent-blue">
                  {count}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Full report */}
      <div className="mx-auto max-w-5xl px-6 pb-8">
        <div className="rounded-xl border border-border-subtle bg-bg-secondary p-6">
          <ReportView report={entry.report} query={entry.query} />
        </div>
      </div>
    </div>
  )
}
