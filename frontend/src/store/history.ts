"use client"

import { create } from "zustand"
import { persist } from "zustand/middleware"

export interface ResearchEntry {
  id: string
  query: string
  report: string | null
  createdAt: string
  agentCount: number
  verifiedClaimsCount: number
  sourcesCount: number
  durationS: number
  toolCalls: Record<string, number>
}

interface HistoryState {
  entries: ResearchEntry[]
  addEntry: (entry: Omit<ResearchEntry, "id" | "createdAt">) => void
  getEntry: (id: string) => ResearchEntry | undefined
  deleteEntry: (id: string) => void
  clearHistory: () => void
}

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export const useHistoryStore = create<HistoryState>()(
  persist(
    (set, get) => ({
      entries: [],

      addEntry: (entry) =>
        set((state) => ({
          entries: [
            {
              ...entry,
              id: generateId(),
              createdAt: new Date().toISOString(),
            },
            ...state.entries,
          ],
        })),

      getEntry: (id) => get().entries.find((e) => e.id === id),

      deleteEntry: (id) =>
        set((state) => ({
          entries: state.entries.filter((e) => e.id !== id),
        })),

      clearHistory: () => set({ entries: [] }),
    }),
    {
      name: "research-history",
    }
  )
)
