"""Fact-Checker node — independently verifies claims in parallel."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.fact_checker_agent import FactCheckerAgent
from app.graph.state import ResearchGraphState
from app.scoring.trust_score import compute_trust_score, label_trust
from app.state.store import StateStore
from app.utils.concurrency import agent_slot

logger = logging.getLogger(__name__)

# ── Circuit breaker threshold ─────────────────────────────────────────────
# If this many consecutive claims fail verification, stop the batch.
CIRCUIT_BREAKER_THRESHOLD = 5

# ── Per-claim timeout (seconds) ───────────────────────────────────────────
CLAIM_TIMEOUT = 120.0


def _validate_fact_check_result(result: dict, claim_text: str) -> dict | None:
    """Validate that a fact-check result has the required shape.

    Returns the result dict if valid, None if malformed (should be rejected).
    """
    if not isinstance(result, dict):
        logger.warning(f"Fact-check result is not a dict for claim: {claim_text[:60]}")
        return None
    required_fields = {
        "claim": (str,),
        "verified": (bool,),
        "trust_score": (int, float),
        "supporting_count": (int,),
        "reasoning": (str,),
    }
    for field, types in required_fields.items():
        if field not in result:
            logger.warning(f"Fact-check result missing '{field}' for claim: {claim_text[:60]}")
            return None
        if not isinstance(result[field], types):
            logger.warning(
                f"Fact-check result field '{field}' has wrong type "
                f"{type(result[field]).__name__} (expected {types}) for claim: {claim_text[:60]}"
            )
            return None
    return result


async def _verify_single_claim(
    claim_text: str,
    stagger_delay: float = 0.0,
    browser_facts: list[str] | None = None,
) -> tuple[dict, list[dict]]:
    """Verify a single claim independently, with timeout.

    Returns (result_dict, claim_specific_sources) so the 5-dimension trust
    score can be computed using the sources actually used for verification,
    not a global top-3 cut from the pooled source set.
    """
    if stagger_delay > 0:
        await asyncio.sleep(stagger_delay)
    async with agent_slot():
        agent = FactCheckerAgent()
        try:
            return await asyncio.wait_for(
                agent.verify_claim_with_evidence(claim_text, browser_facts=browser_facts),
                timeout=CLAIM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(f"Fact-check timed out after {CLAIM_TIMEOUT}s for claim: {claim_text[:60]}")
            return (
                {
                    "claim": claim_text,
                    "verified": False,
                    "trust_score": 10,
                    "supporting_count": 0,
                    "partial_count": 0,
                    "contradict_count": 0,
                    "evidence": [],
                    "reasoning": f"Timeout after {CLAIM_TIMEOUT}s",
                },
                [],  # No sources retrieved before timeout
            )
        except Exception as e:
            logger.error(f"Fact-check crashed for claim {claim_text[:60]}: {e}")
            return (
                {
                    "claim": claim_text,
                    "verified": False,
                    "trust_score": 20,
                    "supporting_count": 0,
                    "partial_count": 0,
                    "contradict_count": 0,
                    "evidence": [],
                    "reasoning": f"Worker error: {str(e)[:100]}",
                },
                [],
            )


async def fact_checker_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Run Fact-Checker agents in parallel across all claims extracted from findings."""
    logger.info("Node: fact_checker")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")
    sse = (config or {}).get("configurable", {}).get("sse")

    # Extract claims from findings
    all_findings = state.get("all_findings", [])
    all_sources = state.get("all_sources", [])

    raw_claims = []
    for finding in all_findings:
        # First try key_facts (ideal format) — these get higher importance
        for fact in finding.get("key_facts", []):
            if fact and len(fact) > 10:
                # Filter out search queries and non-factual statements
                fact_lower = fact.lower().strip()
                is_query = (
                    fact_lower.startswith("i will search")
                    or fact_lower.startswith("searching for")
                    or fact_lower.startswith("query:")
                    or "recent results" in fact_lower and "?" not in fact
                )
                if is_query:
                    logger.info(f"Filtered out search query claim: {fact[:60]}")
                    continue
                raw_claims.append({"text": fact, "importance_score": 100})
        # Fallback: extract sentences from summary if key_facts is empty
        if not finding.get("key_facts") and finding.get("summary"):
            import re
            sentences = re.split(r'[.!?]\s+', finding["summary"])
            for sent in sentences:
                sent = sent.strip()
                if len(sent) > 20 and len(sent) < 300:
                    # Score based on length and specificity (numbers, named entities)
                    score = len(sent)
                    score += sent.count('.') * 30  # multi-sentence = more context
                    score += len(re.findall(r'\d+', sent)) * 20  # has numbers = more specific
                    score += len(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', sent)) * 15  # named entities
                    raw_claims.append({"text": sent, "importance_score": score})

    if not raw_claims:
        logger.info("No claims to fact-check")
        return {**state, "status": "fact_checking_done", "verified_claims": [], "rejected_claims": []}

    # Deduplicate by text similarity (keep highest scored version)
    seen_texts = set()
    deduped = []
    for c in sorted(raw_claims, key=lambda x: x["importance_score"], reverse=True):
        text_lower = c["text"].lower().strip()
        if text_lower not in seen_texts:
            deduped.append(c)
            seen_texts.add(text_lower)

    # Sort by importance and cap
    deduped.sort(key=lambda c: c["importance_score"], reverse=True)
    total_extracted = len(deduped)
    claim_cap = min(24, total_extracted)
    claims_to_check = deduped[:claim_cap]

    logger.info(f"Fact-checking {len(claims_to_check)} claims "
                f"(extracted={total_extracted}, cap={claim_cap})")
    if total_extracted > claim_cap:
        dropped = [c["text"][:60] for c in deduped[claim_cap:]]
        logger.info(f"Dropped {total_extracted - claim_cap} lower-importance claims: {dropped}")

    # Include browser-extracted facts as additional context for the fact-checker
    browser_facts = state.get("browser_facts", [])
    if browser_facts:
        logger.info(f"Passing {len(browser_facts)} browser-extracted facts to fact-checker")

    # Run fact-checkers in parallel — with circuit breaker
    tasks = [
        _verify_single_claim(c["text"], stagger_delay=0, browser_facts=browser_facts)
        for c in claims_to_check
    ]
    if sse:
        for i, claim in enumerate(claims_to_check):
            sse.emit("agent_status", {
                "agent_id": f"fact_checker-{i}",
                "status": "running",
                "claim": claim["text"][:80],
                "model": "gemini-3.5-flash",
                "tier": "fast",
            })
    results = await asyncio.gather(*tasks, return_exceptions=True)
    if sse:
        for i, _pair in enumerate(results):
            if not isinstance(_pair, Exception) and isinstance(_pair, tuple):
                sse.emit("agent_status", {
                    "agent_id": f"fact_checker-{i}",
                    "status": "completed",
                })

    verified_claims = []
    rejected_claims = []
    consecutive_failures = 0

    for i, _pair in enumerate(results):
        # Each worker returns (result_dict, claim_specific_sources)
        if isinstance(_pair, Exception):
            logger.error(f"Fact-check worker {i} failed: {_pair}")
            consecutive_failures += 1
            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                logger.error(
                    f"Fact-check circuit breaker tripped after {consecutive_failures} failures. "
                    f"Rejecting remaining {len(claims_to_check) - i - 1} claims."
                )
                for j in range(i + 1, len(claims_to_check)):
                    rejected_claims.append({
                        "claim": claims_to_check[j]["text"],
                        "reason": "circuit_breaker",
                    })
                break
            continue

        # Unpack (result, claim_specific_sources)
        if isinstance(_pair, tuple) and len(_pair) == 2:
            result, claim_specific_sources = _pair
        else:
            # Backward compat: if for some reason we got a plain dict
            result, claim_specific_sources = _pair, []

        # Validate result shape
        validated = _validate_fact_check_result(result, claims_to_check[i]["text"])
        if validated is None:
            consecutive_failures += 1
            rejected_claims.append({
                "claim": claims_to_check[i]["text"],
                "reason": "malformed_fact_check_result",
            })
            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                logger.error(
                    f"Fact-check circuit breaker tripped after {consecutive_failures} malformed results. "
                    f"Rejecting remaining {len(claims_to_check) - i - 1} claims."
                )
                for j in range(i + 1, len(claims_to_check)):
                    rejected_claims.append({
                        "claim": claims_to_check[j]["text"],
                        "reason": "circuit_breaker",
                    })
                break
            continue

        # Reset circuit breaker on success
        consecutive_failures = 0

        claim_text = validated.get("claim", "")
        importance = claims_to_check[i].get("importance_score", 0) if i < len(claims_to_check) else 0
        fc_trust_score = validated.get("trust_score", 50)
        fc_verified = validated.get("verification", False)
        fc_supporting = validated.get("supporting_count", 0)
        fc_reasoning = validated.get("reasoning", "")[:80]
        logger.info(
            f"Fact-check worker {i}: verified={fc_verified} "
            f"fc_score={fc_trust_score} supporting={fc_supporting} "
            f"claim={claim_text[:60]}"
        )
        # Compute 5-dimension trust score — use claim-specific sources for
        # authority/agreement/recency so each claim gets its own differentiated
        # score (previously all claims scored the same because they shared
        # the global top-3 sources).
        claim_sources_for_scoring = (
            claim_specific_sources if claim_specific_sources
            else all_sources[:3]  # fallback if worker returned no sources
        )
        trust_score = compute_trust_score(
            claim=claim_text,
            sources=claim_sources_for_scoring,
            fact_check_passed=fc_verified,
            fact_check_trust_score=fc_trust_score,
        )

        claim_data = {
            "claim": claim_text,
            "sources": claim_specific_sources[:5] if claim_specific_sources else all_sources[:3],
            "trust_score": trust_score,
            "trust_label": label_trust(trust_score),
            "fact_check_passed": fc_verified,
            "importance_score": importance,
        }

        if trust_score >= 40:
            verified_claims.append(claim_data)
        else:
            rejected_claims.append({"claim": claim_text, "reason": "Low trust score"})

    # Log trust_score distribution
    if verified_claims:
        scores = [c["trust_score"] for c in verified_claims]
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        logger.info(
            f"Fact-check trust_score distribution: "
            f"min={min(scores)} max={max(scores)} avg={sum(scores)/n:.1f} "
            f"median={sorted_scores[n//2]} "
            f"HIGH={sum(1 for s in scores if s >= 81)} "
            f"MODERATE={sum(1 for s in scores if 51 <= s <= 80)} "
            f"LOW={sum(1 for s in scores if s <= 50)}"
        )
    logger.info(
        f"Fact-check complete: {len(verified_claims)} verified, "
        f"{len(rejected_claims)} rejected out of {len(claims_to_check)} checked"
    )

    agent_count = state.get("agent_count", 0) + len(claims_to_check)

    # Persist to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "claims", {
            "verified": verified_claims,
            "rejected": rejected_claims,
        }, agent="fact_checker")
        await store.write_global(session_id, "agent_count", agent_count, agent="fact_checker")
        await store.write_global(session_id, "status", "fact_checking_done", agent="fact_checker")

        # Layer C — add verified claims to citation graph
        citation_graph = store.get_citation_graph(session_id)
        if citation_graph:
            for vc in verified_claims:
                # Extract sub_question_id from the finding that produced this claim
                sub_question_id = None
                for f in all_findings:
                    for fact in f.get("key_facts", []):
                        if fact and fact in vc.get("claim", ""):
                            sub_question_id = f.get("sub_question_id")
                            break

                await citation_graph.add_verified_claim(
                    claim_text=vc.get("claim", ""),
                    trust_score=vc.get("trust_score", 50),
                    trust_label=vc.get("trust_label", "MODERATE"),
                    fact_check_passed=vc.get("fact_check_passed", False),
                    sources=vc.get("sources", []),
                    sub_question_id=sub_question_id,
                )

            # Auto-create RELATED edges between claims sharing sources
            await citation_graph.finalize()

    return {
        **state,
        "verified_claims": verified_claims,
        "rejected_claims": rejected_claims,
        "agent_count": agent_count,
        "status": "fact_checking_done",
    }
