"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Key, Zap, AlertTriangle, CheckCircle, ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/src/components/ui/button";

type Tier = "free" | "custom" | null;

export default function OnboardingPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [selectedTier, setSelectedTier] = useState<Tier>(null);

  // If already authenticated, redirect to dashboard
  useEffect(() => {
    if (status === "authenticated") {
      router.push("/dashboard");
    }
  }, [status, router]);

  const handleFreeTier = () => {
    // Redirect to login page — user can use demo credentials or Google sign-in
    router.push("/login");
  };

  const handleCustomKeys = () => {
    // Redirect to sign-in page, then to settings after sign-in
    router.push("/login?redirect=/settings");
  };

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <Loader2 className="h-6 w-6 animate-spin text-accent-blue" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg-primary">
      <div className="mx-auto max-w-4xl px-6 py-16">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-3xl font-bold text-text-primary mb-3">
            Welcome to Deep Research Swarm
          </h1>
          <p className="text-text-secondary max-w-2xl mx-auto">
            Choose how you want to use the platform. Start with free tier or bring your own API keys for unlimited access.
          </p>
        </div>

        {/* Tier Selection */}
        <div className="grid md:grid-cols-2 gap-6 mb-12">
          {/* Free Tier */}
          <div
            onClick={() => setSelectedTier("free")}
            className={`relative cursor-pointer rounded-2xl border-2 p-8 transition-all ${
              selectedTier === "free"
                ? "border-accent-blue bg-accent-blue/5"
                : "border-border-subtle bg-bg-secondary hover:border-border-strong"
            }`}
          >
            {selectedTier === "free" && (
              <div className="absolute -top-3 right-4 rounded-full bg-accent-blue px-3 py-1 text-xs font-medium text-white">
                Selected
              </div>
            )}
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-green/10 mb-4">
              <Zap className="h-6 w-6 text-accent-green" />
            </div>
            <h3 className="text-xl font-semibold text-text-primary mb-2">Free Tier</h3>
            <p className="text-sm text-text-secondary mb-4">
              Start immediately with shared system API keys. Limited to 1 research query per day.
            </p>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <CheckCircle className="h-4 w-4 text-accent-green" />
                <span>No sign-up required</span>
              </div>
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <CheckCircle className="h-4 w-4 text-accent-green" />
                <span>Full pipeline access</span>
              </div>
              <div className="flex items-center gap-2 text-sm text-accent-yellow">
                <AlertTriangle className="h-4 w-4" />
                <span>1 query per day limit</span>
              </div>
            </div>
          </div>

          {/* Custom Keys Tier */}
          <div
            onClick={() => setSelectedTier("custom")}
            className={`relative cursor-pointer rounded-2xl border-2 p-8 transition-all ${
              selectedTier === "custom"
                ? "border-accent-blue bg-accent-blue/5"
                : "border-border-subtle bg-bg-secondary hover:border-border-strong"
            }`}
          >
            {selectedTier === "custom" && (
              <div className="absolute -top-3 right-4 rounded-full bg-accent-blue px-3 py-1 text-xs font-medium text-white">
                Selected
              </div>
            )}
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-purple/10 mb-4">
              <Key className="h-6 w-6 text-accent-purple" />
            </div>
            <h3 className="text-xl font-semibold text-text-primary mb-2">Bring Your Own Keys</h3>
            <p className="text-sm text-text-secondary mb-4">
              Add your own API keys for unlimited research. Supports OpenRouter, Gemini, Anthropic, Groq, DeepSeek, OpenAI.
            </p>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <CheckCircle className="h-4 w-4 text-accent-green" />
                <span>Unlimited queries</span>
              </div>
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <CheckCircle className="h-4 w-4 text-accent-green" />
                <span>Your quota, your cost</span>
              </div>
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <CheckCircle className="h-4 w-4 text-accent-green" />
                <span>6 providers supported</span>
              </div>
            </div>
          </div>
        </div>

        {/* Continue Button */}
        {selectedTier && (
          <div className="text-center">
            <Button
              size="lg"
              className="h-12 px-8 text-base"
              onClick={selectedTier === "free" ? handleFreeTier : handleCustomKeys}
            >
              {selectedTier === "free" ? "Continue to Login" : "Sign In & Add Keys"}
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>
        )}

        {/* Info Footer */}
        <div className="mt-16 text-center">
          <p className="text-xs text-text-muted">
            Free tier uses shared system API keys with rate limits. Custom keys use your own quota.
            <br />
            You can always add API keys later from Dashboard → Settings.
          </p>
        </div>
      </div>
    </div>
  );
}
