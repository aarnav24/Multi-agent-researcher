"use client"

import { useState } from "react"
import { Search, Loader2 } from "lucide-react"

interface Props {
  onSubmit: (query: string) => void
  disabled: boolean
}

export function QueryInput({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (value.trim() && !disabled) {
      onSubmit(value.trim())
    }
  }

  return (
    <form onSubmit={handleSubmit} className="relative">
      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask a research question..."
        disabled={disabled}
        className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2 pl-10 pr-20 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md bg-accent-blue px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-blue/80 disabled:opacity-50"
      >
        {disabled ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          "Start Research"
        )}
      </button>
    </form>
  )
}
