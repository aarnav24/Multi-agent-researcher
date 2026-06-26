"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { signIn } from "next-auth/react"
import { Search, ArrowRight, Eye, EyeOff } from "lucide-react"
import { Button } from "@/components/ui/button"

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)

    const result = await signIn("credentials", {
      username,
      password,
      redirect: false,
    })

    setLoading(false)

    if (result?.error) {
      setError("Invalid credentials. Username must be 3+ chars, password 6+ chars.")
    } else {
      router.push("/dashboard")
      router.refresh()
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary p-4">
      {/* Background grid */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#27272a_1px,transparent_1px),linear-gradient(to_bottom,#27272a_1px,transparent_1px)] bg-[size:4rem_4rem] opacity-10" />

      <div className="relative w-full max-w-md">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center">
          <div className="mb-4 flex items-center gap-2">
            <div className="h-4 w-4 rounded-full bg-accent-green animate-pulse" />
            <span className="text-lg font-semibold tracking-wide text-text-primary">
              DEEP RESEARCH SWARM
            </span>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-border-subtle bg-bg-secondary px-4 py-1.5">
            <Search className="h-3.5 w-3.5 text-accent-blue" />
            <span className="text-xs text-text-secondary">Multi-Agent AI Research</span>
          </div>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-border-subtle bg-bg-secondary p-8 shadow-2xl">
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-bold text-text-primary">Welcome back</h1>
            <p className="mt-2 text-sm text-text-muted">
              Sign in to access the research dashboard
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-text-primary">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
                className="w-full rounded-lg border border-border-subtle bg-bg-tertiary px-4 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm font-medium text-text-primary">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter password"
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary px-4 py-2.5 pr-10 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="rounded-lg border border-accent-red/30 bg-accent-red/10 px-4 py-2.5 text-xs text-accent-red">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? (
                <span className="animate-pulse">Signing in...</span>
              ) : (
                <>
                  Sign In
                  <ArrowRight className="ml-2 h-4 w-4" />
                </>
              )}
            </Button>
          </form>

          <div className="mt-6 rounded-lg border border-border-subtle bg-bg-tertiary p-3 text-center text-xs text-text-muted">
            Demo: any username (3+ chars) and password (6+ chars)
          </div>
        </div>

        {/* Back to home */}
        <div className="mt-6 text-center">
          <a href="/" className="text-sm text-text-muted hover:text-text-primary transition-colors">
            ← Back to home
          </a>
        </div>
      </div>
    </div>
  )
}
