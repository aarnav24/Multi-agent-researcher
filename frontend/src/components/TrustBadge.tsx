import type { AgentStatus } from "@/src/lib/types"

export function getStatusColor(status: AgentStatus): {
  bg: string
  border: string
  text: string
} {
  switch (status) {
    case "running":
      return { bg: "#eab308", border: "#ca8a04", text: "#eab308" }
    case "completed":
      return { bg: "#22c55e", border: "#16a34a", text: "#22c55e" }
    case "failed":
      return { bg: "#ef4444", border: "#dc2626", text: "#ef4444" }
    default:
      return { bg: "#71717a", border: "#52525b", text: "#71717a" }
  }
}

export function trustColor(score: number): string {
  if (score >= 81) return "#22c55e"
  if (score >= 51) return "#eab308"
  return "#ef4444"
}

export function trustLabel(score: number): string {
  if (score >= 81) return "HIGH"
  if (score >= 51) return "MODERATE"
  return "LOW"
}

export function StatusDot({ status }: { status: AgentStatus }) {
  const colors = getStatusColor(status)
  return (
    <div
      className={`h-2.5 w-2.5 rounded-full ${
        status === "running" ? "animate-pulse" : ""
      }`}
      style={{ backgroundColor: colors.bg }}
    />
  )
}
