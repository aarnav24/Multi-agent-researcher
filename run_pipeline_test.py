"""Quick pipeline test — runs the full graph and prints results with timing + trust scores."""

import asyncio
import io
import logging
import sys
import time

# Fix Windows console encoding for emoji
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Enable INFO-level logging for our modules
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)
logging.getLogger("app.graph.nodes.fact_checker").setLevel(logging.INFO)
logging.getLogger("app.agents.fact_checker_agent").setLevel(logging.INFO)
logging.getLogger("app.agents.base").setLevel(logging.INFO)

from app.graph.research_graph import build_graph
from app.graph.state import ResearchGraphState
from app.agents.base import llm_timing, reset_all_keys
from app.state.store import StateStore


async def main():
    query = "What are the latest advances in quantum computing hardware, error correction techniques, open-source quantum programming frameworks, and industry developments?"

    # Reset key rotation so every run starts fresh from key 1
    reset_all_keys()
    llm_timing.reset()

    # Pre-load embedding model BEFORE running pipeline (blocks until ready)
    print("Pre-loading embedding model...")
    t0 = time.time()
    from app.utils.embeddings import embed_texts
    embed_texts(["warmup"])
    print(f"  Embedding model loaded in {time.time() - t0:.1f}s")

    # Create shared state store (connects to Redis/Postgres, falls back to in-memory)
    store = StateStore()
    await store.connect()

    # Create session in shared store
    await store.create_session("test-pipeline", query)

    initial_state: ResearchGraphState = {
        "session_id": "test-pipeline",
        "query": query,
        "plan": None,
        "plan_ready": False,
        "sub_questions": [],
        "active_searchers": 0,
        "active_browsers": 0,
        "all_findings": [],
        "all_sources": [],
        "critic_rounds": 0,
        "critic_gaps": [],
        "critic_done": False,
        "verified_claims": [],
        "rejected_claims": [],
        "final_report": None,
        "citations_verified": False,
        "status": "created",
        "agent_count": 0,
        "error": None,
        "sufficiency_met": False,
        "searcher_rounds": 0,
        "browser_facts": [],
    }

    graph = build_graph()
    llm_timing.reset()  # fresh timing for each run

    # Inject StateStore into graph via config
    graph_config = {"configurable": {"store": store}}

    print("=" * 70)
    print(f"DEEP RESEARCH PIPELINE TEST")
    print(f"Query: {query}")
    print("=" * 70)

    node_times = {}
    current_node = None
    node_start = None
    total_start = time.time()
    # Track the latest output per node to reconstruct final state
    latest_outputs = {}

    last_chunk_time = None
    async for chunk in graph.astream(initial_state, config=graph_config):
        now = time.time()
        last_chunk_time = now
        for node_name, node_output in chunk.items():
            # When a new node's chunk arrives, the previous node has finished.
            # The chunk is emitted only after the node completes, so now
            # is effectively the end time of the previous node.
            if current_node and current_node != node_name:
                elapsed = now - node_start
                node_times[current_node] = elapsed
                print(f"  [{current_node}] done in {elapsed:.1f}s")
            if current_node != node_name:
                current_node = node_name
                node_start = now
                print(f"\n>> [{node_name}]")

            latest_outputs[node_name] = node_output

            if node_name == "searchers":
                findings = node_output.get("all_findings", [])
                sources = node_output.get("all_sources", [])
                print(f"  Findings: {len(findings)} | Sources: {len(sources)}")

            elif node_name == "browsers":
                sources = node_output.get("all_sources", [])
                full = sum(1 for s in sources if s.get("full_content"))
                browser_facts = node_output.get("browser_facts", [])
                print(f"  Browser fetches with content: {full}")
                print(f"  Browser-extracted facts: {len(browser_facts)}")

            elif node_name == "critic":
                gaps = node_output.get("critic_gaps", [])
                done = node_output.get("critic_done", False)
                print(f"  Critic gaps: {len(gaps)} | Done: {done}")

            elif node_name == "sufficiency_check":
                met = node_output.get("sufficiency_met", False)
                print(f"  Sufficiency met: {met}")

            elif node_name == "fact_checker":
                verified = node_output.get("verified_claims", [])
                rejected = node_output.get("rejected_claims", [])
                print(f"  Verified: {len(verified)} | Rejected: {len(rejected)}")
                for vc in verified:
                    score = vc.get("trust_score", 0)
                    label = vc.get("trust_label", "LOW")
                    claim_text = vc.get("claim", "")[:80]
                    print(f"     [{label} {score}/100] {claim_text}...")

    # Final node timing — the last node's chunk arrives only after it
    # completes, so we can't measure its wall-clock from chunk arrival.
    # Use the LLM call duration as a lower-bound estimate.
    if current_node and current_node not in node_times:
        # Map node name to agent name for LLM timing lookup
        agent_name = current_node.replace("_node", "").replace("_dispatch", "").replace("_check", "") + "Agent"
        llm_call_time = 0.0
        for tier_stats in llm_timing.summary().values():
            if agent_name in tier_stats.get("agents", {}):
                llm_call_time = tier_stats["agents"][agent_name]["total_s"]
                break
        node_times[current_node] = llm_call_time

    total_time = time.time() - total_start

    # Merge all outputs to get final state
    final_state = dict(initial_state)
    for output in latest_outputs.values():
        if isinstance(output, dict):
            final_state.update(output)

    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)

    print(f"\nTIMING:")
    for node, t in node_times.items():
        bar = "#" * max(1, int(t / 2))
        print(f"  {node:25s} {t:6.1f}s  {bar}")
    print(f"  {'TOTAL':25s} {total_time:6.1f}s")

    verified = final_state.get("verified_claims", [])
    report = final_state.get("final_report", "")
    agent_count = final_state.get("agent_count", 0)
    sources = final_state.get("all_sources", [])
    findings = final_state.get("all_findings", [])
    status = final_state.get("status", "unknown")

    print(f"\nRESULTS:")
    print(f"  Status:          {status}")
    print(f"  Agent count:     {agent_count}")
    print(f"  Findings:        {len(findings)}")
    print(f"  Sources:         {len(sources)}")
    print(f"  Verified claims: {len(verified)}")
    print(f"  Report length:   {len(report)} chars")

    if verified:
        print(f"\nTRUST SCORES:")
        for i, vc in enumerate(verified, 1):
            score = vc.get("trust_score", 0)
            label = vc.get("trust_label", "LOW")
            claim_text = vc.get("claim", "")
            sources_count = len(vc.get("sources", []))
            bar_len = int(score / 5)
            bar = "+" * bar_len + "-" * (20 - bar_len)
            print(f"  {i}. [{label:8s} {score:3d}/100] [{bar}] ({sources_count} src)")
            print(f"     {claim_text[:100]}")

        avg_score = sum(v.get("trust_score", 0) for v in verified) / len(verified)
        high = sum(1 for v in verified if v.get("trust_label") == "HIGH")
        mod = sum(1 for v in verified if v.get("trust_label") == "MODERATE")
        low = sum(1 for v in verified if v.get("trust_label") == "LOW")
        print(f"\n  Average trust score: {avg_score:.0f}/100")
        print(f"  HIGH: {high} | MODERATE: {mod} | LOW: {low}")

    # ── LLM Timing + Token + Key Usage Summary ──────────────────────────────
    timing = llm_timing.summary()
    if timing:
        print(f"\nLLM CALL TIMING & TOKEN USAGE (by model tier):")
        print("=" * 70)
        grand_total_llm = 0
        grand_total_calls = 0
        grand_total_in = 0
        grand_total_out = 0
        for tier, stats in timing.items():
            print(f"\n  [{tier.upper()}]")
            print(f"    Calls:          {stats['count']}")
            print(f"    Total time:     {stats['total_s']:.1f}s")
            print(f"    Avg time:       {stats['avg_s']:.1f}s per call")
            print(f"    Min/Max:        {stats['min_s']:.1f}s / {stats['max_s']:.1f}s")
            print(f"    Input tokens:   {stats['total_input_tokens']:,}")
            print(f"    Output tokens:  {stats['total_output_tokens']:,}")
            print(f"    Total tokens:   {stats['total_input_tokens'] + stats['total_output_tokens']:,}")
            # Key distribution
            key_counts = {}
            for c in timing[tier].get('_raw_calls', []):
                k = c.get('key_idx')
                if k is not None:
                    key_counts[k] = key_counts.get(k, 0) + 1
            if key_counts:
                print(f"    Key distribution: ", end="")
                for k in sorted(key_counts):
                    print(f"key{k}={key_counts[k]}  ", end="")
                print()
            print(f"    --- Per Agent ---")
            for agent, astats in sorted(stats['agents'].items()):
                print(f"      {agent:30s} calls={astats['count']}  "
                      f"time={astats['total_s']:.1f}s  "
                      f"in={astats['in_tokens']:,}t  out={astats['out_tokens']:,}t")
            grand_total_llm += stats['total_s']
            grand_total_calls += stats['count']
            grand_total_in += stats['total_input_tokens']
            grand_total_out += stats['total_output_tokens']
        print(f"\n  {'TOTAL':30s} calls={grand_total_calls}  time={grand_total_llm:.1f}s  "
              f"in={grand_total_in:,}t  out={grand_total_out:,}t")
        print(f"  LLM overhead: {grand_total_llm/total_time*100:.0f}% of pipeline")

    if report:
        print(f"\nREPORT PREVIEW (first 2000 chars):")
        print("-" * 70)
        print(report[:2000])
        if len(report) > 2000:
            print(f"\n  ... ({len(report) - 2000} more characters)")

    # ── Shared Store Summary ──────────────────────────────────────────────
    # Read store state directly from in-memory dict (final_state from LangGraph is the source of truth)
    print(f"\nSHARED STORE STATE:")
    store_session = store._memory_sessions.get("test-pipeline")
    if store_session:
        print(f"  Status:          {store_session.status}")
        print(f"  Sub-questions:   {len(store_session.sub_questions)}")
        print(f"  Findings:        {len(store_session.findings)}")
        print(f"  Sources:         {len(store_session.sources)}")
        print(f"  Verified claims: {len(store_session.verified_claims)}")
        print(f"  Agent count:     {store_session.agent_count}")
        print(f"  Searcher rounds: {store_session.searcher_rounds}")
        print(f"  Report length:   {len(store_session.final_report or '')} chars")
    else:
        print("  Session not found in store memory!")
    # Show audit log from memory
    audit = [e for e in store._audit_log if e.session_id == "test-pipeline"]
    print(f"  Audit entries:   {len(audit)}")
    if audit:
        for a in audit[:8]:
            print(f"    seq={a.seq} {a.event_type} by {a.agent}")
        if len(audit) > 8:
            print(f"    ... and {len(audit) - 8} more")

    # ── Citation Graph (Layer C) ─────────────────────────────────────────
    citation_graph = store.get_citation_graph("test-pipeline")
    if citation_graph and citation_graph._adapter.enabled:
        print(f"\nCITATION GRAPH:")
        stats = await citation_graph.get_stats()
        print(f"  Claims:          {stats.get('claims', 0)}")
        print(f"  Sources:         {stats.get('sources', 0)}")
        print(f"  Sub-questions:   {stats.get('sub_questions', 0)}")
        print(f"  SUPPORTS edges:  {stats.get('supports', 0)}")
        print(f"  RELATED edges:   {stats.get('related', 0)}")
    else:
        print(f"\nCITATION GRAPH: Neo4j not available (graph disabled)")

    # Cleanup
    await store.disconnect()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
