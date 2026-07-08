"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { signIn } from "next-auth/react"
import { Search, ArrowRight, Eye, EyeOff, UserPlus } from "lucide-react"
import { Button } from "@/src/components/ui/button"

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

    try {
      const result = await signIn("credentials", {
        username,
        password,
        redirect: false,
      })

      if (result?.error) {
        setError("Invalid credentials. Username/email must be 3+ chars, password 6+ chars.")
      } else {
        router.push("/dashboard")
        router.refresh()
      }
    } catch (err: any) {
      setError("Invalid credentials. Username/email or password incorrect.")
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSignIn = async () => {
    setError("")
    setLoading(true)
    try {
      const { signInWithPopup } = await import("firebase/auth")
      const { firebaseAuth, googleProvider } = await import("@/src/lib/firebase")
      const result = await signInWithPopup(firebaseAuth, googleProvider)
      const idToken = await result.user.getIdToken()

      // Verify token with backend and establish NextAuth session
      const res = await fetch("/api/v1/auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken }),
      })

      if (res.ok) {
        // Create user in database if they don't exist (Google sign-in)
        const email = result.user.email || ""
        const name = result.user.displayName || email.split("@")[0] || "Google User"
        const googleUid = result.user.uid

        // Try to create the user (will fail with 409 if already exists, which is fine)
        await fetch("/api/v1/auth/signup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: googleUid,
            email: email || undefined,
            password: googleUid,
            name: name,
          }),
        }).catch(() => {}) // Ignore errors (user may already exist)

        // Now sign in via credentials
        const signInResult = await signIn("credentials", {
          username: googleUid,
          password: googleUid,
          email: email || undefined,
          name: name,
          redirect: false,
        })

        if (signInResult?.error) {
          setError("Google sign-in failed. Please try again.")
        } else {
          router.push("/dashboard")
          router.refresh()
        }
      } else {
        setError("Google sign-in verification failed. Please try again.")
      }
    } catch (err: any) {
      if (err?.code === "auth/popup-closed-by-user") {
        // User closed popup silently
      } else {
        setError("Google sign-in failed. Please try again.")
      }
    } finally {
      setLoading(false)
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

          {/* Divider */}
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border-subtle" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-bg-secondary px-3 text-text-muted">or</span>
            </div>
          </div>

          {/* Google Sign In */}
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={loading}
            className="flex w-full items-center justify-center gap-3 rounded-lg border border-border-subtle bg-bg-tertiary px-4 py-2.5 text-sm font-medium text-text-primary transition-all hover:bg-bg-hover hover:border-border-strong disabled:opacity-50"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            Continue with Google
          </button>

          {/* Sign Up Link */}
          <div className="mt-5 text-center text-sm text-text-muted">
            New here?{" "}
            <button
              onClick={() => router.push("/signup")}
              className="font-medium text-accent-blue hover:text-accent-blue/80 transition-colors inline-flex items-center gap-1"
            >
              <UserPlus className="h-3.5 w-3.5" />
              Create account
            </button>
          </div>

          <div className="mt-4 rounded-lg border border-border-subtle bg-bg-tertiary p-3 text-center text-xs text-text-muted">
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
