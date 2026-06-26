"use client"

import { useState } from "react"
import { CheckCircle, Copy, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ReportViewProps {
  report: string | null
  query: string
}

export function ReportView({ report, query }: ReportViewProps) {
  const [copied, setCopied] = useState(false)

  if (!report) return null

  const handleCopy = async () => {
    await navigator.clipboard.writeText(report)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-accent-blue" />
          <span className="text-sm font-medium text-text-primary">Final Report</span>
        </div>
        <div className="relative">
          <Button
            variant="outline"
            size="sm"
            onClick={handleCopy}
            className="h-8 px-3 text-xs"
          >
            <Copy className="h-3.5 w-3.5 mr-1.5" />
            {copied ? "Copied!" : "Copy Report"}
          </Button>
          {copied && (
            <div className="absolute -top-8 right-0 rounded-md bg-accent-green px-2 py-1 text-xs text-white shadow-lg animate-pulse">
              Copied!
            </div>
          )}
        </div>
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
