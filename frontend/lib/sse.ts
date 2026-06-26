import { useResearchStore } from "./store"
import type { SSEEvent, SSEEventType } from "./types"

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"

export async function startResearch(query: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_agents: 15 }),
  })
  if (!res.ok) throw new Error(`Failed to start research: ${res.statusText}`)
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
        const data = JSON.parse((e as MessageEvent).data)
        store.processSSEEvent({ event: eventName as SSEEventType, data })
      } catch (err) {
        console.error(`Failed to parse ${eventName} event:`, err)
      }
    })
  })

  eventSource.onerror = () => {
    console.error("SSE connection error")
    const state = useResearchStore.getState()
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
