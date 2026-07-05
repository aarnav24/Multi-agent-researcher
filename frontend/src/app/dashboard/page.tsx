"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useSession, signOut } from "next-auth/react"
import { useRouter } from "next/navigation"
import { LogOut, User, History, FileText, Key, CheckCircle, X, Sparkles, FileUp, Loader2 } from "lucide-react"
import { useResearchStore } from "@/src/lib/store"
import { useHistoryStore } from "@/src/store/history"
import { startResearch, connectToStream, uploadCorpusDocument, userHasCorpusDocs } from "@/src/lib/sse"
import { QueryInput } from "@/src/components/QueryInput"
import { AgentTree } from "@/src/components/AgentTree"
import { AgentInspector } from "@/src/components/AgentInspector"
import { CitationGraph } from "@/src/components/CitationGraph"
import { CostTicker } from "@/src/components/CostTicker"
import { ReportView } from "@/src/components/ReportView"
import { Button } from "@/src/components/ui/button"

export default function Dashboard() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const { query, status: researchStatus, isStreaming, finalReport, setSession, reset, setFinalReport } = useResearchStore()
  const { addEntry } = useHistoryStore()
  const [sseCleanup, setSseCleanup] = useState<(() => void) | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [showSuccessPopup, setShowSuccessPopup] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Document upload state — minimal: just track whether the user has docs
  // and surface a transient "uploading…" hint. Backend is the source of truth
  // for the actual list; the orchestrator re-checks `has_documents` per run.
  const [hasCorpus, setHasCorpus] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadNotice, setUploadNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [tickerHeight, setTickerHeight] = useState(250)
  const [isResizing, setIsResizing] = useState(false)

  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const container = document.getElementById("right-panel-container")
      if (container) {
        const rect = container.getBoundingClientRect()
        const newHeight = moveEvent.clientY - rect.top
        setTickerHeight(Math.max(120, Math.min(newHeight, rect.height - 120)))
      }
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      document.removeEventListener("mousemove", handleMouseMove)
      document.removeEventListener("mouseup", handleMouseUp)
    }

    document.addEventListener("mousemove", handleMouseMove)
    document.addEventListener("mouseup", handleMouseUp)
  }, [])

  // Pre-flight check: does this user already have indexed docs?
  useEffect(() => {
    if (!session) return
    let cancelled = false
    userHasCorpusDocs().then((v) => {
      if (!cancelled) setHasCorpus(v)
    })
    return () => {
      cancelled = true
    }
  }, [session])

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

  // When research completes, save to history (only once per session) and show success popup
  const savedRef = useRef(false)
  useEffect(() => {
    if (researchStatus === "done" && finalReport && !savedRef.current) {
      savedRef.current = true
      setShowSuccessPopup(true)

      // Count actual data from the research — use the SAME source of truth
      // as the live dashboard (costStats.agentsActive = peak agents spawned)
      // so the history row matches what the user saw during the run.
      const store = useResearchStore.getState()
      const agents = store.agents
      const costStats = store.costStats
      const citationNodes = store.citationNodes
      const agentCount = costStats.agentsActive || agents.size
      const toolCallMap: Record<string, number> = {}
      agents.forEach((agent) => {
        const calls = agent.toolCalls || []
        calls.forEach((tc) => {
          toolCallMap[tc.toolName] = (toolCallMap[tc.toolName] || 0) + 1
        })
      })

      // Estimate duration from agent timestamps
      let totalDuration = 0
      agents.forEach((agent) => {
        if (agent.startTime && agent.endTime) {
          totalDuration += (agent.endTime - agent.startTime) / 1000
        }
      })

      // Verified claims = real Claim nodes in the citation store (not a
      // heuristic parse of the report text).
      const verifiedClaimsCount = citationNodes.filter((n) => n.type === "Claim").length
      // Sources = real Source nodes in the citation store.
      const sourcesCount = citationNodes.filter((n) => n.type === "Source").length

      addEntry({
        query,
        report: finalReport,
        agentCount,
        verifiedClaimsCount,
        sourcesCount,
        durationS: Math.round(totalDuration),
        toolCalls: toolCallMap,
      })
    }
    if (researchStatus !== "done") {
      savedRef.current = false
    }
  }, [researchStatus, finalReport, query, addEntry])

  // Auto-dismiss success popup after 8 seconds
  useEffect(() => {
    if (showSuccessPopup) {
      const timer = setTimeout(() => setShowSuccessPopup(false), 8000)
      return () => clearTimeout(timer)
    }
  }, [showSuccessPopup])

  const handleStartResearch = useCallback(
    async (queryText: string) => {
      reset()
      setShowReport(false)
      setError(null)
      try {
        const sessionId = await startResearch(queryText)
        setSession(sessionId, queryText)
        const cleanup = connectToStream(sessionId)
        setSseCleanup(() => cleanup)
      } catch (err: any) {
        // Surface rate-limit and other errors to the user
        setError(err?.message || "Failed to start research. Please try again.")
      }
    },
    [reset, setSession]
  )

  const [abortController, setAbortController] = useState<AbortController | null>(null);

  const handleUploadClick = () => fileInputRef.current?.click()

  const handleFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    // Reset the input so the same file can be re-selected later.
    e.target.value = ""
    if (!file) return

    // Cancel previous ongoing upload if any
    abortController?.abort()

    setUploading(true)
    setUploadNotice(null)

    const controller = new AbortController()
    setAbortController(controller)

    try {
      const formData = new FormData()
      formData.append("file", file)
      // Include user_id if needed — backend extracts from Auth header
      const result = await fetch("/api/v1/corpus/upload", {
        method: "POST",
        headers: {
          // Authorization: `Bearer ${user_id}`, // assumes auth token handled elsewhere
        },
        body: formData,
        signal: controller.signal,
      })

      const payload = await result.json()

      if (!result.ok) {
        throw new Error(payload?.detail || "Upload failed")
      }

      setHasCorpus(true)
      setUploadNotice({
        kind: "ok",
        text: `Indexed "${payload.doc_name}" (${payload.chunks_indexed} chunks).
        ${file.type === "application/pdf" ? "PDF text extracted and indexed." : "Text content included."} The next research run will search it.`,
      })
    } catch (err: any) {
      if (!controller.signal.aborted) {
        setUploadNotice({ kind: "err", text: err.message || "Upload failed." })
      }
    } finally {
      setUploading(false)
      setAbortController(null)
      // Auto-dismiss the notice after a few seconds.
      setTimeout(() => setUploadNotice(null), 5000)
    }
  }

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
        {/* Hidden file input — opened programmatically by the upload button */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf"
          className="hidden"
          onChange={handleFileChosen}
        />
        {/* Document upload — pgvector searches these on the next run. */}
        <div className="relative mr-2">
          <Button
            variant="outline"
            size="sm"
            className={`h-8 px-3 text-xs ${
              hasCorpus ? "border-accent-purple/40 bg-accent-purple/10 text-accent-purple hover:bg-accent-purple/15" : ""
            }`}
            onClick={handleUploadClick}
            disabled={uploading}
            title={hasCorpus ? "Documents indexed — upload more" : "Upload a document (.txt/.md) to include in your research"}
          >
            {uploading ? (
              <>
                <div className="progress-bar progress-active" />
                <button
                  onClick={() => {
                    abortController?.abort()
                    setUploading(false)
                    setUploadNotice({ kind: "err", text: "Upload cancelled." })
                    setAbortController(null)
                  }}
                  className="ml-2 text-xs text-accent-red hover:text-accent-red/80"
                >
                  Cancel
                </button>
              </>
            ) : (
              <FileUp className="h-3.5 w-3.5 mr-1.5" />
            )}
            {uploading ? "Uploading…" : hasCorpus ? "Add Doc" : "Upload Doc"}
          </Button>
          {hasCorpus && !uploading && (
            <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-purple opacity-60" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-purple" />
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Report toggle button — always visible when report is ready */}
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
          <Button variant="ghost" size="icon" className="h-8 w-8" title="Research History" onClick={() => router.push("/history")}>
            <History className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" title="API Key Settings" onClick={() => router.push("/settings")}>
            <Key className="h-4 w-4" />
          </Button>
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

      {/* Error Banner */}
      {error && (
        <div className="border-b border-accent-red/30 bg-accent-red/10 px-6 py-2.5">
          <div className="mx-auto flex max-w-4xl items-center justify-between">
            <p className="text-xs text-accent-red">{error}</p>
            <button
              onClick={() => setError(null)}
              className="text-accent-red/60 hover:text-accent-red text-xs"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Success Popup */}
      {showSuccessPopup && (
        <div className="fixed top-20 left-1/2 z-50 -translate-x-1/2 animate-slide-down">
          <div className="relative flex items-center gap-4 rounded-2xl border border-accent-green/40 bg-accent-green/15 px-6 py-4 shadow-2xl backdrop-blur-sm">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-green/20">
              <CheckCircle className="h-5 w-5 text-accent-green" />
            </div>
            <div className="flex items-center gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent-green" />
                  <span className="text-sm font-semibold text-accent-green">
                    Report Generated Successfully!
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {query.length > 50 ? query.slice(0, 47) + "..." : query}
                </p>
              </div>
              <Button
                size="sm"
                onClick={() => {
                  setShowReport(true)
                  setShowSuccessPopup(false)
                }}
                className="ml-3 h-9 bg-accent-green text-white hover:bg-accent-green/90 shadow-lg shadow-accent-green/20"
              >
                <FileText className="h-4 w-4 mr-2" />
                View Report
              </Button>
            </div>
            <button
              onClick={() => setShowSuccessPopup(false)}
              className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-bg-secondary text-text-muted hover:text-text-primary transition-colors border border-border-subtle"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        </div>
      )}

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
          <section id="right-panel-container" className="flex w-1/2 flex-col relative" style={{ userSelect: isResizing ? "none" : "auto" }}>
            <div style={{ height: tickerHeight }} className="overflow-y-auto border-b border-border-subtle flex-shrink-0">
              <CostTicker />
            </div>
            {/* Drag Handle splitter */}
            <div
              onMouseDown={startResize}
              className="h-1.5 w-full cursor-row-resize bg-border-subtle hover:bg-accent-blue/50 active:bg-accent-blue transition-colors flex-shrink-0 flex items-center justify-center"
            >
              <div className="h-0.5 w-8 bg-text-muted/30 rounded" />
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
