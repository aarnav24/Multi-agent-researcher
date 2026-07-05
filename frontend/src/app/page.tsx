"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowRight, Search, Globe, Zap, Shield, BarChart3, Code2, Database, Cpu, Layers, GitBranch, Activity, CheckCircle, FileSearch } from "lucide-react"
import { Button } from "@/src/components/ui/button"
import SignInModal from "@/src/components/SignInModal"
import SignUpModal from "@/src/components/SignUpModal"

const features = [
  {
    icon: <Search className="h-6 w-6" />,
    title: "Multi-Agent Research",
    description: "AI agents collaborate to research any topic — Searchers, Browsers, Fact-Checkers, and Critics working in parallel.",
  },
  {
    icon: <BarChart3 className="h-6 w-6" />,
    title: "Real-Time Dashboard",
    description: "Watch agents work live with react-flow visualization. See every tool call, status change, and citation as it happens.",
  },
  {
    icon: <Shield className="h-6 w-6" />,
    title: "Trust Scoring",
    description: "Every claim is independently verified with 5-dimension trust scoring: authority, agreement, recency, fact-check, and internal consistency.",
  },
  {
    icon: <Globe className="h-6 w-6" />,
    title: "Citation Graph",
    description: "Neo4j-powered knowledge graph connecting claims, sources, and sub-questions. Click any node to explore the evidence chain.",
  },
  {
    icon: <Zap className="h-6 w-6" />,
    title: "Intelligent Routing",
    description: "Planner assigns optimal tools per sub-question: arXiv for papers, GitHub for code, Serper/Tavily for news, pgvector for internal docs.",
  },
  {
    icon: <Code2 className="h-6 w-6" />,
    title: "Built with LangGraph",
    description: "Orchestrator-worker pattern with stateless async agents, slot-based write isolation, and circuit breakers.",
  },
]

const stats = [
  { value: "10+", label: "AI Agents" },
  { value: "8+", label: "Search Tools" },
  { value: "5-dim", label: "Trust Score" },
  { value: "Real-time", label: "SSE Stream" },
]

const techStack = [
  { name: "Python", desc: "Core backend logic" },
  { name: "TypeScript", desc: "Type-safe full-stack" },
  { name: "Next.js", desc: "React dashboard" },
  { name: "FastAPI", desc: "Backend framework with SSE streaming" },
  { name: "LangGraph", desc: "Multi-agent orchestration" },
  { name: "react-flow", desc: "Agent graph visualization" },
  { name: "Neo4j", desc: "Citation knowledge graph" },
  { name: "PostgreSQL", desc: "State store + pgvector" },
  { name: "Redis", desc: "Hot state cache" },
  { name: "Docker", desc: "Containerized deployment" },
  { name: "Langfuse", desc: "LLM observability & tracing" },
  { name: "OpenTelemetry", desc: "System traces & metrics" },
]

const tools = [
  { name: "Tavily", description: "LLM-optimized web content with advanced search depth" },
  { name: "Serper", description: "Google Search API for maximum freshness" },
  { name: "Exa.ai", description: "Semantic-first search, ideal for academic content" },
  { name: "arXiv", description: "Structured metadata for research papers and preprints" },
  { name: "GitHub", description: "Repo search, README extraction, code analysis" },
  { name: "DuckDuckGo", description: "Unlimited free fallback search — never runs out" },
  { name: "Playwright", description: "JS-rendered pages, PDFs, paywalled previews" },
  { name: "pgvector", description: "User-uploaded document search via vector similarity" },
]

export default function LandingPage() {
  const [signInOpen, setSignInOpen] = useState(false)
  const [signUpOpen, setSignUpOpen] = useState(false)

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Modals */}
      <SignInModal
        isOpen={signInOpen}
        onClose={() => setSignInOpen(false)}
        onSwitchToSignUp={() => {
          setSignInOpen(false)
          setSignUpOpen(true)
        }}
      />
      <SignUpModal
        isOpen={signUpOpen}
        onClose={() => setSignUpOpen(false)}
        onSwitchToSignIn={() => {
          setSignUpOpen(false)
          setSignInOpen(true)
        }}
      />

      {/* Navigation */}
      <nav className="sticky top-0 z-50 border-b border-border-subtle bg-bg-primary/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-accent-green animate-pulse" />
            <span className="text-sm font-semibold tracking-wide text-text-primary">
              DEEP RESEARCH SWARM
            </span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="#features" className="text-sm text-text-muted hover:text-text-primary transition-colors">
              Features
            </Link>
            <Link href="#architecture" className="text-sm text-text-muted hover:text-text-primary transition-colors">
              Architecture
            </Link>
            <Button variant="outline" size="sm" onClick={() => setSignInOpen(true)}>
              Sign In
            </Button>
            <Button size="sm" onClick={() => window.location.href = "/onboarding"}>
              Start Research
              <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden">
        {/* Grid background */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#27272a_1px,transparent_1px),linear-gradient(to_bottom,#27272a_1px,transparent_1px)] bg-[size:4rem_4rem] opacity-20 [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_110%)]" />

        <div className="relative mx-auto max-w-6xl px-6 pt-24 pb-32">
          <div className="flex flex-col items-center text-center">
            {/* Badge */}
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border-subtle bg-bg-secondary px-4 py-1.5">
              <div className="h-2 w-2 rounded-full bg-accent-yellow animate-pulse" />
              <span className="text-xs text-text-secondary">
                Multi-Agent AI Research System
              </span>
            </div>

            {/* Heading */}
            <h1 className="max-w-4xl text-5xl font-bold tracking-tight text-text-primary sm:text-6xl lg:text-7xl">
              Research any topic with{" "}
              <span className="bg-gradient-to-r from-accent-blue to-accent-purple bg-clip-text text-transparent">
                10+ AI Agents
              </span>
            </h1>

            <p className="mt-6 max-w-2xl text-lg text-text-secondary">
              Watch AI agents collaborate in real-time to research, fact-check, and synthesize
              comprehensive reports with full citation graphs and trust scores.
            </p>

            {/* CTA */}
            <div className="mt-10 flex gap-4">
              <Button
                size="lg"
                className="h-12 px-8 text-base"
                onClick={() => setSignUpOpen(true)}
              >
                Launch Dashboard
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
              <Button variant="outline" size="lg" className="h-12 px-8 text-base" onClick={() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })}>
                Learn More
              </Button>
            </div>

            {/* Stats */}
            <div className="mt-16 grid grid-cols-2 gap-8 sm:grid-cols-4">
              {stats.map((stat) => (
                <div key={stat.label} className="text-center">
                  <div className="text-2xl font-bold text-text-primary">{stat.value}</div>
                  <div className="mt-1 text-xs text-text-muted">{stat.label}</div>
                </div>
              ))}
            </div>

            {/* Live Stats Preview */}
            <div className="mt-16 w-full max-w-4xl rounded-xl border border-border-subtle bg-bg-secondary p- shadow-2xl">
              <div className="flex items-center gap-2 border-b border-border-subtle px-4 py-3">
                <div className="h-3 w-3 rounded-full bg-accent-red" />
                <div className="h-3 w-3 rounded-full bg-accent-yellow" />
                <div className="h-3 w-3 rounded-full bg-accent-green" />
                <span className="ml-3 text-xs text-text-muted">Deep Research Swarm — Sample Run Stats</span>
              </div>
              <div className="p-6">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
                  <div className="rounded-lg bg-bg-tertiary p-5 text-center">
                    <div className="text-3xl font-bold text-accent-blue">14</div>
                    <div className="mt-1.5 text-sm text-text-muted">Agents Spawned</div>
                  </div>
                  <div className="rounded-lg bg-bg-tertiary p-5 text-center">
                    <div className="text-3xl font-bold text-accent-purple">23</div>
                    <div className="mt-1.5 text-sm text-text-muted">LLM Calls</div>
                  </div>
                  <div className="rounded-lg bg-bg-tertiary p-5 text-center">
                    <div className="text-3xl font-bold text-accent-green">47</div>
                    <div className="mt-1.5 text-sm text-text-muted">Tool Calls</div>
                  </div>
                  <div className="rounded-lg bg-bg-tertiary p-5 text-center">
                    <div className="text-3xl font-bold text-accent-yellow">12</div>
                    <div className="mt-1.5 text-sm text-text-muted">Claims Verified</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-t border-border-subtle py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="text-center">
            <h2 className="text-3xl font-bold text-text-primary">Everything you need</h2>
            <p className="mt-3 text-text-secondary">
              A production-grade multi-agent research system with real-time observability.
            </p>
          </div>
          <div className="mt-16 grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="group rounded-xl border border-border-subtle bg-bg-secondary p-6 transition-colors hover:border-border-strong"
              >
                <div className="mb-4 inline-flex rounded-lg bg-bg-tertiary p-3 text-accent-blue transition-colors group-hover:bg-accent-blue/10">
                  {feature.icon}
                </div>
                <h3 className="mb-2 text-lg font-semibold text-text-primary">{feature.title}</h3>
                <p className="text-sm text-text-muted">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Architecture */}
      <section id="architecture" className="border-t border-border-subtle py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="text-center">
            <h2 className="text-3xl font-bold text-text-primary">How it works</h2>
            <p className="mt-3 text-text-secondary">
              Orchestrator-worker pattern with stateless agents and shared memory.
            </p>
          </div>

          {/* Architecture Diagram — full width */}
          <div className="mt-16 rounded-xl border border-border-subtle bg-bg-secondary p-8">
            <h3 className="mb-10 text-center text-sm font-semibold uppercase tracking-wider text-text-muted">
              Agent Pipeline — Parallel Execution Flow
            </h3>

            {/* Pipeline Diagram — vertical flow */}
            <div className="relative max-w-3xl mx-auto">

              {/* 1. User Query */}
              <div className="flex justify-center mb-2">
                <div className="rounded-lg border-2 border-accent-blue/40 bg-accent-blue/10 px-8 py-4 text-center w-full max-w-md">
                  <div className="text-base font-semibold text-accent-blue">User Query</div>
                  <div className="mt-1 text-sm text-text-muted">The research question to investigate</div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-2">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* 2. Planner */}
              <div className="flex justify-center mb-2">
                <div className="rounded-lg border border-accent-purple/50 bg-accent-purple/10 px-8 py-4 text-center w-full max-w-md">
                  <div className="text-base font-semibold text-accent-purple">Planner</div>
                  <div className="mt-1 text-sm text-text-muted">Hypothesis tree + search strategy</div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-2">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* 3. Lead Orchestrator */}
              <div className="flex justify-center mb-2">
                <div className="rounded-lg border border-sky-400/50 bg-sky-400/10 px-8 py-4 text-center w-full max-w-md">
                  <div className="text-base font-semibold text-sky-400">Lead Orchestrator</div>
                  <div className="mt-1 text-sm text-text-muted">Decomposes into 3–8 sub-questions + assigns tools</div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-5">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* Row 1: Searchers + Browsers (parallel) */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
                <div className="rounded-lg border border-accent-blue/30 bg-bg-tertiary p-4">
                  <div className="mb-3 text-center">
                    <GitBranch className="h-5 w-5 mx-auto text-accent-blue mb-1" />
                    <div className="text-sm font-semibold text-accent-blue">Searcher Agents</div>
                    <div className="text-xs text-text-muted">3–8 parallel workers (one per sub-question)</div>
                  </div>
                  <div className="space-y-1.5">
                    {["Sub-question → Search", "Query normalization", "Multi-tool synthesis"].map((s) => (
                      <div key={s} className="rounded bg-accent-blue/10 px-2 py-1 text-center text-xs text-accent-blue">
                        {s}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-accent-green/30 bg-bg-tertiary p-4">
                  <div className="mb-3 text-center">
                    <Globe className="h-5 w-5 mx-auto text-accent-green mb-1" />
                    <div className="text-sm font-semibold text-accent-green">Browser Workers</div>
                    <div className="text-xs text-text-muted">2–4 parallel workers</div>
                  </div>
                  <div className="space-y-1.5">
                    {["Deep URL fetch", "JS rendering", "Content extraction"].map((s) => (
                      <div key={s} className="rounded bg-accent-green/10 px-2 py-1 text-center text-xs text-accent-green">
                        {s}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-5">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* Row 2: Critic + Fact-Checker (parallel) */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
                <div className="rounded-lg border border-accent-yellow/30 bg-bg-tertiary p-4">
                  <div className="mb-3 text-center">
                    <Activity className="h-5 w-5 mx-auto text-accent-yellow mb-1" />
                    <div className="text-sm font-semibold text-accent-yellow">Critic</div>
                    <div className="text-xs text-text-muted">Gap analysis + loop decision (max 2 rounds)</div>
                  </div>
                  <div className="space-y-1.5">
                    {["Find gaps", "Contradictions", "Loop or proceed"].map((s) => (
                      <div key={s} className="rounded bg-accent-yellow/10 px-2 py-1 text-center text-xs text-accent-yellow">
                        {s}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-lg border border-accent-red/30 bg-bg-tertiary p-4">
                  <div className="mb-3 text-center">
                    <CheckCircle className="h-5 w-5 mx-auto text-accent-red mb-1" />
                    <div className="text-sm font-semibold text-accent-red">Fact-Checker Agents</div>
                    <div className="text-xs text-text-muted">Parallel claim verification</div>
                  </div>
                  <div className="space-y-1.5">
                    {["Claim extraction", "Independent search", "Trust score (5-dim)"].map((s) => (
                      <div key={s} className="rounded bg-accent-red/10 px-2 py-1 text-center text-xs text-accent-red">
                        {s}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-2">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* 4. Synthesizer */}
              <div className="flex justify-center mb-2">
                <div className="rounded-lg border-2 border-cyan-400/40 bg-cyan-400/10 px-8 py-4 text-center w-full max-w-md">
                  <div className="text-base font-semibold text-cyan-400">Synthesizer</div>
                  <div className="mt-1 text-sm text-text-muted">Integrates all findings → coherent report</div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-2">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* 5. Citation Formatter */}
              <div className="flex justify-center mb-2">
                <div className="rounded-lg border-2 border-accent-yellow/40 bg-accent-yellow/10 px-8 py-4 text-center w-full max-w-md">
                  <div className="text-base font-semibold text-accent-yellow">Citation Formatter</div>
                  <div className="mt-1 text-sm text-text-muted">Embeds verified citations into the final report</div>
                </div>
              </div>

              {/* Arrow */}
              <div className="flex justify-center mb-2">
                <div className="flex flex-col items-center">
                  <div className="h-6 w-0.5 bg-border-strong" />
                  <div className="h-0 w-0 border-l-[5px] border-r-[5px] border-t-[7px] border-l-transparent border-r-transparent border-t-border-strong" />
                </div>
              </div>

              {/* 6. Final Report */}
              <div className="flex justify-center">
                <div className="rounded-lg border border-accent-green/50 bg-accent-green/10 px-8 py-4 text-center w-full max-w-md">
                  <div className="text-base font-semibold text-accent-green">Final Report</div>
                  <div className="mt-1 text-sm text-text-muted">Claims + Trust scores + Citations</div>
                </div>
              </div>
            </div>
          </div>

          {/* Below diagram: Tech Stack + Tools in half-half */}
          <div className="mt-10 grid gap-6 md:grid-cols-2 items-start">
            {/* Tech Stack */}
            <div className="rounded-xl border border-border-subtle bg-bg-secondary p-6">
              <div className="mb-5 flex items-center gap-2">
                <Cpu className="h-5 w-5 text-accent-blue" />
                <h3 className="text-base font-semibold uppercase tracking-wider text-text-primary">
                  Tech Stack
                </h3>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {techStack.map((tech) => (
                  <div key={tech.name} className="rounded-lg bg-bg-tertiary px-4 py-3">
                    <div className="text-sm font-medium text-text-primary">{tech.name}</div>
                    <div className="text-xs text-text-muted mt-0.5">{tech.desc}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Tools */}
            <div className="rounded-xl border border-border-subtle bg-bg-secondary p-6">
              <div className="mb-5 flex items-center gap-2">
                <Layers className="h-5 w-5 text-accent-purple" />
                <h3 className="text-base font-semibold uppercase tracking-wider text-text-primary">
                  Tools
                </h3>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {tools.map((tool) => (
                  <div key={tool.name} className="rounded-lg bg-bg-tertiary px-4 py-3">
                    <div className="text-sm font-medium text-text-primary">{tool.name}</div>
                    <div className="mt-1 text-xs text-text-muted">{tool.description}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border-subtle py-24">
        <div className="mx-auto max-w-4xl px-6 text-center">
          <h2 className="text-3xl font-bold text-text-primary">
            Ready to see it in action?
          </h2>
          <p className="mt-3 text-text-secondary">
            Sign in and start researching. Watch agents collaborate in real-time.
          </p>
          <Button
            size="lg"
            className="mt-8 h-12 px-8 text-base"
            onClick={() => window.location.href = '/onboarding'}
          >
            Get Started
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border-subtle py-8">
        <div className="mx-auto max-w-6xl px-6 text-center text-xs text-text-muted">
          Deep Research Swarm — Multi-Agent AI Research System
        </div>
      </footer>
    </div>
  )
}
