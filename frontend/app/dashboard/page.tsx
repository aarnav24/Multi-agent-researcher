"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useSession, signOut } from "next-auth/react"
import { useRouter } from "next/navigation"
import { LogOut, User, History, FileText } from "lucide-react"
import { useResearchStore } from "@/lib/store"
import { useHistoryStore } from "@/store/history"
import { startResearch, connectToStream } from "@/lib/sse"
import { QueryInput } from "@/components/QueryInput"
import { AgentTree } from "@/components/AgentTree"
import { AgentInspector } from "@/components/AgentInspector"
import { CitationGraph } from "@/components/CitationGraph"
import { CostTicker } from "@/components/CostTicker"
import { ReportView } from "@/components/ReportView"
import { Button } from "@/components/ui/button"

export default function Dashboard() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const { query, status: researchStatus, isStreaming, finalReport, setSession, reset, setFinalReport } = useResearchStore()
  const { addEntry } = useHistoryStore()
  const [sseCleanup, setSseCleanup] = useState<(() => void) | null>(null)
  const [showReport, setShowReport] = useState(false)

  // Redirect if not authenticated
  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login")
    }
  }, [status, router])

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (sseCleanup) sseCleanup()
    }
  }, [sseCleanup])

  // When research completes, save to history (only once per session)
  const savedRef = useRef(false)
  useEffect(() => {
    if (researchStatus === "done" && finalReport && !savedRef.current) {
      savedRef.current = true
      addEntry({
        query,
        report: finalReport,
        agentCount: 0,
        verifiedClaimsCount: 0,
        sourcesCount: 0,
        durationS: 0,
        toolCalls: {},
      })
    }
    if (researchStatus !== "done") {
      savedRef.current = false
    }
  }, [researchStatus, finalReport, query, addEntry])

  const handleStartResearch = useCallback(
    async (queryText: string) => {
      reset()
      setShowReport(false)
      const sessionId = await startResearch(queryText)
      setSession(sessionId, queryText)
      const cleanup = connectToStream(sessionId)
      setSseCleanup(() => cleanup)
    },
    [reset, setSession]
  )

  const handleLogout = () => {
    if (sseCleanup) sseCleanup()
    signOut({ callbackUrl: "/" })
  }

  // Loading state
  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <div className="flex flex-col items-center gap-3">
          <div className="h-3 w-3 rounded-full bg-accent-blue animate-pulse" />
          <span className="text-sm text-text-muted">Loading session...</span>
        </div>
      </div>
    )
  }

  // Not authenticated
  if (!session) return null

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Top Bar */}
      <header className="flex items-center gap-4 border-b border-border-subtle bg-bg-secondary px-6 py-3">
        <div className="flex items-center gap-2">
          <div className="h-3 w-3 rounded-full bg-accent-green animate-pulse" />
          <h1 className="text-sm font-semibold tracking-wide text-text-primary">
            DEEP RESEARCH SWARM
          </h1>
        </div>
        <div className="flex-1">
          <QueryInput onSubmit={handleStartResearch} disabled={isStreaming} />
        </div>
        <div className="flex items-center gap-3">
          {/* Report toggle button */}
          {finalReport && researchStatus === "done" && (
            <Button
              variant={showReport ? "default" : "outline"}
              size="sm"
              onClick={() => setShowReport(!showReport)}
              className="h-8 px-3 text-xs"
            >
              <FileText className="h-3.5 w-3.5 mr-1.5" />
              {showReport ? "Hide Report" : "View Report"}
            </Button>
          )}
          <span
            className={`rounded-full px-2 py-0.5 text-xs ${
              isStreaming
                ? "bg-accent-yellow/20 text-accent-yellow"
                : researchStatus === "done"
                ? "bg-accent-green/20 text-accent-green"
                : "bg-bg-tertiary text-text-muted"
            }`}
          >
            {isStreaming ? "LIVE" : researchStatus.toUpperCase()}
          </span>
          <Link href="/history">
            <Button variant="ghost" size="icon" className="h-8 w-8" title="Research History">
              <History className="h-4 w-4" />
            </Button>
          </Link>
          <div className="flex items-center gap-2 border-l border-border-subtle pl-3">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <User className="h-3.5 w-3.5" />
              {session.user?.name || "User"}
            </div>
            <Button variant="ghost" size="icon" onClick={handleLogout} className="h-8 w-8">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      {showReport && finalReport ? (
        /* Report View */
        <main className="flex-1 overflow-hidden">
          <ReportView report={finalReport} query={query} />
        </main>
      ) : (
        /* Dashboard View */
        <main className="flex flex-1 overflow-hidden">
          {/* Left Panel: Agent Tree + Inspector */}
          <section className="flex w-1/2 flex-col border-r border-border-subtle">
            <div className="flex-1 overflow-hidden">
              <AgentTree />
            </div>
            <div className="h-64 border-t border-border-subtle">
              <AgentInspector />
            </div>
          </section>

          {/* Right Panel: Cost + Citations */}
          <section className="flex w-1/2 flex-col">
            <div className="border-b border-border-subtle">
              <CostTicker />
            </div>
            <div className="flex-1 overflow-hidden">
              <CitationGraph />
            </div>
          </section>
        </main>
      )}
    </div>
  )
}
