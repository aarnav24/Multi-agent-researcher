"use client"

import { useState } from "react"
import { CheckCircle, Copy, FileText, ShieldCheck } from "lucide-react"
import { Button } from "@/src/components/ui/button"

interface ReportViewProps {
  report: string | null
  query: string
}

// Matches trust annotations the synthesizer is instructed to emit, e.g.
//   — Trust: HIGH (74/100)
//   - [Source: Title](url) — Trust: MODERATE (60/100)
//   Trust: LOW (30/100)
const TRUST_LINE_REGEX = /Trust:\s*(HIGH|MODERATE|LOW)\s*\((\d+)\s*\/\s*100\)/i
// Looser fallback for LLM drift (score-first, missing "Trust:" prefix)
const TRUST_LOOSE_REGEX = /\b(HIGH|MODERATE|LOW)\s*[:(-]\s*(\d+)\s*\/\s*100\)/i

function trustColor(label: string): string {
  switch (label.toUpperCase()) {
    case "HIGH":
      return "#22c55e"
    case "MODERATE":
      return "#eab308"
    case "LOW":
      return "#ef4444"
    default:
      return "#71717a"
  }
}

export function ReportView({ report, query }: ReportViewProps) {
  const [copied, setCopied] = useState(false)

  if (!report) return null

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(report)
    } catch {
      // Fallback for non-secure contexts
      const textarea = document.createElement("textarea")
      textarea.value = report
      textarea.style.position = "fixed"
      textarea.style.opacity = "0"
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand("copy")
      document.body.removeChild(textarea)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-accent-blue" />
          <span className="text-sm font-medium text-text-primary">Final Report</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleCopy}
          className={`h-8 px-3 text-xs transition-all duration-300 ${
            copied
              ? "bg-accent-green/20 border-accent-green/50 text-accent-green"
              : "hover:bg-accent-green/10 hover:border-accent-green/30"
          }`}
        >
          {copied ? (
            <>
              <CheckCircle className="h-3.5 w-3.5 mr-1.5" />
              Copied!
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5 mr-1.5" />
              Copy Report
            </>
          )}
        </Button>
      </div>

      {/* Report content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mb-3 rounded-lg bg-bg-tertiary px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-text-muted mb-1">Research Query</div>
          <div className="text-sm text-text-secondary">{query}</div>
        </div>

        <div className="rounded-lg border border-border-subtle bg-bg-secondary p-4">
          <div className="prose prose-sm prose-invert max-w-none">
            {report.split("\n").map((line, i) => {
              if (line.startsWith("# ")) {
                return <h1 key={i} className="text-lg font-bold text-text-primary mb-3">{line.slice(2)}</h1>
              }
              if (line.startsWith("## ")) {
                return <h2 key={i} className="text-base font-semibold text-text-primary mt-4 mb-2">{line.slice(3)}</h2>
              }
              if (line.startsWith("### ")) {
                return <h3 key={i} className="text-sm font-semibold text-text-primary mt-3 mb-1">{line.slice(4)}</h3>
              }
              // Inline trust annotation? Render text + colored badge.
              // Try the strict pattern first, then the loose fallback.
              const trustMatch = TRUST_LINE_REGEX.exec(line) || TRUST_LOOSE_REGEX.exec(line)
              const base = line.startsWith("- ") || line.startsWith("* ") ? line.slice(2) : line
              if (trustMatch) {
                const label = trustMatch[1].toUpperCase()
                const score = parseInt(trustMatch[2], 10)
                const color = trustColor(label)
                // Strip the trust annotation from the visible text so it
                // doesn't appear twice (once raw, once as the badge).
                const text = base.replace(TRUST_LINE_REGEX, "").replace(TRUST_LOOSE_REGEX, "").replace(/[-—]\s*$/, "").trim()
                const Tag = line.startsWith("- ") || line.startsWith("* ") ? "li" : "p"
                return (
                  <Tag key={i} className="text-sm text-text-secondary ml-4 mb-1 inline-flex items-center gap-2 flex-wrap">
                    {text && <span>{text}</span>}
                    <span
                      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold"
                      style={{ backgroundColor: `${color}20`, color }}
                    >
                      <ShieldCheck className="h-2.5 w-2.5" />
                      {label} {score}
                    </span>
                  </Tag>
                )
              }
              if (line.startsWith("- ") || line.startsWith("* ")) {
                return <li key={i} className="text-sm text-text-secondary ml-4 mb-1">{line.slice(2)}</li>
              }
              if (line.trim() === "") {
                return <br key={i} />
              }
              return <p key={i} className="text-sm text-text-secondary mb-2">{line}</p>
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
