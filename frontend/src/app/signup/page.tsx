"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { ArrowLeft, Eye, EyeOff, UserPlus, Mail, Lock, User } from "lucide-react";
import { Button } from "@/src/components/ui/button";

export default function SignUpPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (name.length < 2) {
      setError("Name must be at least 2 characters.");
      return;
    }

    setLoading(true);

    try {
      // Step 1: Create user in backend
      const res = await fetch("/api/v1/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: name,
          email: email || undefined,
          password,
          name,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || "Sign up failed. Please try again.");
        setLoading(false);
        return;
      }

      // Step 2: Sign in with NextAuth
      const result = await signIn("credentials", {
        username: name,
        password,
        redirect: false,
      });

      setLoading(false);

      if (result?.error) {
        setError("Sign up succeeded but login failed. Please try logging in.");
      } else {
        router.push("/dashboard");
        router.refresh();
      }
    } catch (err: any) {
      setLoading(false);
      setError("Sign up failed. Please try again.");
    }
  };

  const handleGoogleSignUp = async () => {
    setError("")
    setLoading(true)
    try {
      const { signInWithPopup } = await import("firebase/auth")
      const { firebaseAuth, googleProvider } = await import("@/src/lib/firebase")
      const result = await signInWithPopup(firebaseAuth, googleProvider)
      const idToken = await result.user.getIdToken()

      // Verify token with backend
      const res = await fetch("/api/v1/auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken }),
      })

      if (res.ok) {
        // Create user in database
        const email = result.user.email || ""
        const name = result.user.displayName || email.split("@")[0] || "Google User"
        const googleUid = result.user.uid

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

        // Sign in via credentials
        const signInResult = await signIn("credentials", {
          username: googleUid,
          password: googleUid,
          redirect: false,
        })

        if (signInResult?.error) {
          setError("Google sign-up failed. Please try again.")
        } else {
          router.push("/dashboard")
          router.refresh()
        }
      } else {
        setError("Google sign-up verification failed. Please try again.")
      }
    } catch (err: any) {
      if (err?.code === "auth/popup-closed-by-user") {
        // User closed popup silently
      } else {
        setError("Google sign-up failed. Please try again.")
      }
    } finally {
      setLoading(false)
    }
  };

  return (
    <div className="min-h-screen bg-bg-primary">
      <div className="mx-auto max-w-md px-6 py-16">
        <button
          onClick={() => router.push("/login")}
          className="mb-8 flex items-center gap-2 text-sm text-text-muted hover:text-text-primary transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to login
        </button>

        <div className="text-center mb-8">
          <div className="mb-4 flex items-center justify-center gap-2">
            <div className="h-4 w-4 rounded-full bg-accent-green animate-pulse" />
            <span className="text-lg font-semibold tracking-wide text-text-primary">
              DEEP RESEARCH SWARM
            </span>
          </div>
          <h1 className="text-2xl font-bold text-text-primary">Create your account</h1>
          <p className="mt-2 text-sm text-text-muted">
            Sign up to start researching with AI agents
          </p>
        </div>

        <div className="rounded-xl border border-border-subtle bg-bg-secondary p-8 shadow-2xl">
          <button
            type="button"
            onClick={handleGoogleSignUp}
            disabled={true}
            className="flex w-full items-center justify-center gap-3 rounded-lg border border-border-subtle bg-bg-tertiary px-4 py-2.5 text-sm font-medium text-text-muted cursor-not-allowed opacity-50"
          >
            Google sign up (coming soon)
          </button>

          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border-subtle" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-bg-secondary px-3 text-text-muted">or sign up with email</span>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">Full Name</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="John Doe"
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue" />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">Email (optional)</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com"
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue" />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min 6 characters"
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-10 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue" />
                <button type="button" onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors">
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">Confirm Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input type={showPassword ? "text" : "password"} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Re-enter password"
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none focus:ring-1 focus:ring-accent-blue" />
              </div>
            </div>

            {error && (
              <div className="rounded-lg border border-accent-red/30 bg-accent-red/10 px-4 py-2.5 text-xs text-accent-red">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={loading}>
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

          <div className="mt-5 text-center text-sm text-text-muted">
            Already have an account?{" "}
            <button onClick={() => router.push("/login")} className="font-medium text-accent-blue hover:text-accent-blue/80 transition-colors">
              Sign in
            </button>
          </div>
        </div>

        <div className="mt-6 rounded-lg border border-border-subtle bg-bg-secondary p-4 text-center">
          <p className="text-xs text-text-muted">
            Free tier includes 10 research queries per day. Add your own API keys in Settings for unlimited access.
          </p>
        </div>
      </div>
    </div>
  );
}
