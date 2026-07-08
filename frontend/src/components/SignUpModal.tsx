"use client"

import { useState, useEffect, useCallback } from "react"
import { X, Eye, EyeOff, UserPlus, Mail, Lock, User } from "lucide-react"
import { Button } from "@/src/components/ui/button"
import { signIn } from "next-auth/react"
import { firebaseAuth, googleProvider } from "@/src/lib/firebase"
import {
  createUserWithEmailAndPassword,
  signInWithPopup,
  updateProfile,
} from "firebase/auth"

interface SignUpModalProps {
  isOpen: boolean
  onClose: () => void
  onSwitchToSignIn: () => void
}

export default function SignUpModal({
  isOpen,
  onClose,
  onSwitchToSignIn,
}: SignUpModalProps) {
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)
  const [mounted, setMounted] = useState(false)

  // Handle mount animation
  useEffect(() => {
    if (isOpen) {
      // Small delay so the element is in the DOM before animating
      requestAnimationFrame(() => setMounted(true))
    } else {
      setMounted(false)
    }
  }, [isOpen])

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) onClose()
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [isOpen, onClose])

  // Lock body scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => {
      document.body.style.overflow = ""
    }
  }, [isOpen])

  const resetForm = useCallback(() => {
    setName("")
    setEmail("")
    setPassword("")
    setConfirmPassword("")
    setError("")
    setShowPassword(false)
  }, [])

  const handleClose = useCallback(() => {
    onClose()
    // Reset after animation completes
    setTimeout(resetForm, 300)
  }, [onClose, resetForm])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    if (password.length < 6) {
      setError("Password must be at least 6 characters.")
      return
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.")
      return
    }
    if (name.length < 2) {
      setError("Name must be at least 2 characters.")
      return
    }

    setLoading(true)

    try {
      // Create user in Firebase
      const credential = await createUserWithEmailAndPassword(
        firebaseAuth,
        email,
        password
      )
      // Update display name
      await updateProfile(credential.user, { displayName: name })

      // Also sign in via NextAuth credentials so the session is established
      await signIn("credentials", {
        username: name,
        password,
        redirect: false,
      })

      handleClose()
      window.location.href = "/dashboard"
    } catch (err: any) {
      const code = err?.code || ""
      if (code === "auth/email-already-in-use") {
        setError("An account with this email already exists. Please sign in.")
      } else if (code === "auth/invalid-email") {
        setError("Invalid email address.")
      } else if (code === "auth/weak-password") {
        setError("Password is too weak. Use at least 6 characters.")
      } else {
        setError(err?.message || "Sign up failed. Please try again.")
      }
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSignUp = async () => {
    setError("")
    setGoogleLoading(true)

    try {
      // Sign up with Firebase Google
      const result = await signInWithPopup(firebaseAuth, googleProvider)

      // Verify the token with the backend before trusting the identity
      const idToken = await result.user.getIdToken()
      const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"
      const verifyRes = await fetch(`${API_BASE}/api/v1/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken }),
      })

      if (!verifyRes.ok) {
        throw new Error("Identity verification failed. Please try again.")
      }

      const verifiedUser = await verifyRes.json()

      // Establish NextAuth session with the VERIFIED identity
      await signIn("credentials", {
        username: verifiedUser.uid,
        password: verifiedUser.uid,
        email: verifiedUser.email,
        name: verifiedUser.name,
        redirect: false,
      })

      handleClose()
      window.location.href = "/dashboard"
    } catch (err: any) {
      const code = err?.code || ""
      if (code === "auth/popup-closed-by-user") {
        // User closed popup, no error to show
      } else if (code === "auth/account-exists-with-different-credential") {
        setError("An account with this email already exists via another method. Please sign in.")
      } else {
        setError(err?.message || "Google sign up failed. Please try again.")
      }
    } finally {
      setGoogleLoading(false)
    }
  }

  if (!isOpen && !mounted) return null

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center p-4 transition-all duration-300 ease-out ${
        mounted && isOpen
          ? "opacity-100 pointer-events-auto"
          : "opacity-0 pointer-events-none"
      }`}
    >
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ${
          mounted && isOpen ? "opacity-100" : "opacity-0"
        }`}
        onClick={handleClose}
      />

      {/* Modal */}
      <div
        className={`relative w-full max-w-md transform transition-all duration-300 ease-out ${
          mounted && isOpen
            ? "scale-100 opacity-100 translate-y-0"
            : "scale-95 opacity-0 translate-y-4"
        }`}
      >
        {/* Glow effect */}
        <div className="absolute -inset-1 rounded-2xl bg-gradient-to-r from-accent-blue/20 via-accent-purple/20 to-accent-blue/20 opacity-50 blur-xl" />

        <div className="relative rounded-xl border border-border-subtle bg-bg-secondary shadow-2xl">
          {/* Header */}
          <div className="relative flex items-center justify-between border-b border-border-subtle px-6 py-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-blue/10">
                <UserPlus className="h-4 w-4 text-accent-blue" />
              </div>
              <h2 className="text-lg font-semibold text-text-primary">Create Account</h2>
            </div>
            <button
              onClick={handleClose}
              className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body */}
          <div className="p-6">
            {/* Google Sign Up */}
            <button
              type="button"
              onClick={handleGoogleSignUp}
              disabled={googleLoading || loading}
              className="flex w-full items-center justify-center gap-3 rounded-lg border border-border-subtle bg-bg-tertiary px-4 py-2.5 text-sm font-medium text-text-primary transition-all hover:bg-bg-hover hover:border-border-strong disabled:opacity-50"
            >
              {googleLoading ? (
                <span className="flex items-center gap-2">
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Connecting...
                </span>
              ) : (
                <>
                  <svg className="h-5 w-5" viewBox="0 0 24 24">
                    <path
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                      fill="#4285F4"
                    />
                    <path
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                      fill="#34A853"
                    />
                    <path
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                      fill="#FBBC05"
                    />
                    <path
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                      fill="#EA4335"
                    />
                  </svg>
                  Continue with Google
                </>
              )}
            </button>

            {/* Divider */}
            <div className="relative my-5">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-border-subtle" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-bg-secondary px-3 text-text-muted">or sign up with email</span>
              </div>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-3.5">
              {/* Name */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Full Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="John Doe"
                    className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue transition-colors"
                  />
                </div>
              </div>

              {/* Email */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue transition-colors"
                  />
                </div>
              </div>

              {/* Password */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Min 6 characters"
                    className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-10 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue transition-colors"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {/* Confirm Password */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                  <input
                    type={showPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter password"
                    className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue transition-colors"
                  />
                </div>
              </div>

              {error && (
                <div className="rounded-lg border border-accent-red/30 bg-accent-red/10 px-4 py-2.5 text-xs text-accent-red">
                  {error}
                </div>
              )}

              <Button type="submit" className="w-full" disabled={loading || googleLoading}>
                {loading ? (
                  <span className="flex items-center gap-2">
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Creating account...
                  </span>
                ) : (
                  <>
                    <UserPlus className="mr-2 h-4 w-4" />
                    Create Account
                  </>
                )}
              </Button>
            </form>

            {/* Switch to sign in */}
            <div className="mt-5 text-center text-sm text-text-muted">
              Already have an account?{" "}
              <button
                onClick={() => {
                  handleClose()
                  onSwitchToSignIn()
                }}
                className="font-medium text-accent-blue hover:text-accent-blue/80 transition-colors"
              >
                Sign in
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
