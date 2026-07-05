import { useResearchStore } from "./store"
import type { SSEEvent, SSEEventType } from "./types"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"

/**
 * Get the current user's ID for the Authorization header.
 * Uses session.user.id (UUID from database) if available, falls back to name.
 * Returns empty string if not authenticated (anonymous usage).
 */
async function getUserId(): Promise<string> {
  try {
    const res = await fetch("/api/auth/session")
    if (res.ok) {
      const session = await res.json()
      if (session?.user) {
        // Prefer UUID (user.id), fall back to name for backward compat
        return session.user.id || session.user.name || ""
      }
    }
  } catch {
    // Silently fall back to anonymous
  }
  return ""
}

/**
 * Extract user-friendly error from a failed research start response.
 * Handles 429 (rate limit) with the backend's detail message.
 */
async function getErrorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (data.detail) return data.detail
  } catch {
    // ignore parse errors
  }
  if (res.status === 429) {
    return "Daily limit reached. Free tier allows 1 research per day. Add your own API keys in Settings for unlimited access."
  }
  return `Failed to start research: ${res.statusText}`
}

export async function startResearch(query: string): Promise<string> {
  const user_id = await getUserId()
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (user_id) {
    headers["Authorization"] = `Bearer ${user_id}`
  }

  const res = await fetch(`${API_BASE}/api/v1/research`, {
    method: "POST",
    headers,
    body: JSON.stringify({ query, max_agents: 15 }),
  })

  if (!res.ok) {
    throw new Error(await getErrorMessage(res))
  }

  const data = await res.json()
  return data.session_id
}

export function connectToStream(sessionId: string): () => void {
  const store = useResearchStore.getState()
  const url = `${API_BASE}/api/v1/research/${sessionId}/stream`

  const eventSource = new EventSource(url)

  const eventNames = [
    "agent_start",
    "agent_complete",
    "agent_status",
    "tool_call",
    "finding",
    "claim_verified",
    "citation_update",
    "cost_update",
    "timing_summary",
    "done",
    "error",
  ]

  eventNames.forEach((eventName) => {
    eventSource.addEventListener(eventName, (e) => {
      try {
        const raw = (e as MessageEvent).data
        // Guard against malformed frames (empty/undefined data, keepalive
        // frames slipping through as event payloads, non-object JSON).
        if (!raw || raw === "undefined" || raw === "null") return
        const data = JSON.parse(raw)
        if (typeof data !== "object" || data === null) return
        store.processSSEEvent({ event: eventName as SSEEventType, data })
      } catch (err) {
        console.error(`Failed to parse ${eventName} event:`, err)
      }
    })
  })

  eventSource.onerror = () => {
    const state = useResearchStore.getState()
    if (state.status === "done" || state.status === "failed") {
      eventSource.close()
      return
    }
    console.error("SSE connection error")
    if (state.isStreaming) {
      setTimeout(() => {
        eventSource.close()
        connectToStream(sessionId)
      }, 3000)
    }
  }

  store.setStreaming(true)

  return () => {
    eventSource.close()
    store.setStreaming(false)
  }
}

export async function fetchCitationGraph(sessionId: string) {
  const res = await fetch(`${API_BASE}/api/v1/research/${sessionId}/graph`)
  if (!res.ok) throw new Error("Failed to fetch citation graph")
  return res.json()
}

/**
 * Upload a document to the user's pgvector corpus so searchers can search it.
 * Accepts .txt and .md (multipart/form-data). Anonymous users are rejected by
 * the backend with 401.
 */
export async function uploadCorpusDocument(file: File): Promise<{ doc_name: string; chunks_indexed: number }> {
  const user_id = await getUserId()
  const form = new FormData()
  form.append("file", file)

  const res = await fetch(`${API_BASE}/api/v1/corpus/upload`, {
    method: "POST",
    headers: user_id ? { Authorization: `Bearer ${user_id}` } : {},
    body: form,
  })

  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      if (data?.detail) msg = data.detail
    } catch {
      /* ignore */
    }
    throw new Error(msg || `Upload failed: ${res.statusText}`)
  }
  return res.json()
}

/**
 * Cheap preflight so the dashboard can decide whether to surface the
 * "documents will be searched" hint before kicking off a research run.
 */
export async function userHasCorpusDocs(): Promise<boolean> {
  const user_id = await getUserId()
  if (!user_id) return false
  try {
    const res = await fetch(`${API_BASE}/api/v1/corpus/has-documents`, {
      headers: { Authorization: `Bearer ${user_id}` },
      cache: "no-store",
    })
    if (!res.ok) return false
    const data = await res.json()
    return Boolean(data?.has_documents)
  } catch {
    return false
  }
}
