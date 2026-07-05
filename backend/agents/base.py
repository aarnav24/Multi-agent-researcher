"""Base agent — LLM wrapper supporting Groq and Google Gemini providers.

- Groq: primary provider for all agents (fast + reasoning tiers)
- Gemini: primary for FactCheckerAgent, fallback for reasoning tier
- OpenRouter: commented out but preserved for easy switching

Set LLM_PROVIDER in .env to "groq" or "openrouter" to switch.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time

# tiktoken for token counting — imported lazily in _LLMTimingTracker
from typing import Any, Callable, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from backend.config import settings
from backend.observability import observe, get_langfuse_context

logger = logging.getLogger(__name__)

# ── LLM call timing tracker ──────────────────────────────────────────────────

class _LLMTimingTracker:
    """Global tracker for LLM call latencies and token usage, keyed by tier."""

    def __init__(self):
        self._calls: dict[str, list[dict]] = {"reasoning": [], "fast": []}
        self._encoder = None  # lazy-init tiktoken encoder

    def _get_encoder(self):
        """Lazy-init tiktoken encoder for token counting."""
        if self._encoder is None:
            try:
                import tiktoken
                self._encoder = tiktoken.get_encoding("cl100k_base")  # works for all LLMs
            except Exception as e:
                logger.warning(f"tiktoken not available: {e}. Token counting disabled.")
                self._encoder = False
        return self._encoder

    def count_tokens(self, text: str) -> int:
        """Count tokens in a string using tiktoken. Falls back to ~4 chars/token."""
        enc = self._get_encoder()
        if enc is False:
            return len(text) // 4  # rough fallback: ~4 chars per token
        return len(enc.encode(text))

    def record(self, tier: str, agent: str, model: str, latency_s: float,
               input_tokens: int = 0, output_tokens: int = 0, key_idx: int | None = None):
        entry = {
            "latency_s": latency_s,
            "agent": agent,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "key_idx": key_idx,
        }
        self._calls.setdefault(tier, []).append(entry)
        key_str = f" key={key_idx}" if key_idx is not None else ""
        logger.info(
            f"LLM timing [{tier}] {agent} ({model}): {latency_s:.1f}s | "
            f"in={input_tokens}t out={output_tokens}t{key_str}"
        )

    def summary(self) -> dict:
        result = {}
        for tier, calls in sorted(self._calls.items()):
            if calls:
                total_in = sum(c["input_tokens"] for c in calls)
                total_out = sum(c["output_tokens"] for c in calls)
                times = [c["latency_s"] for c in calls]
                # Per-agent breakdown
                agents = {}
                for c in calls:
                    a = c["agent"]
                    if a not in agents:
                        agents[a] = {"count": 0, "total_s": 0, "in_tokens": 0, "out_tokens": 0}
                    agents[a]["count"] += 1
                    agents[a]["total_s"] += c["latency_s"]
                    agents[a]["in_tokens"] += c["input_tokens"]
                    agents[a]["out_tokens"] += c["output_tokens"]
                # Per-model breakdown
                models = {}
                for c in calls:
                    m = c["model"]
                    if m not in models:
                        models[m] = {"count": 0, "total_s": 0, "in_tokens": 0, "out_tokens": 0}
                    models[m]["count"] += 1
                    models[m]["total_s"] += c["latency_s"]
                    models[m]["in_tokens"] += c["input_tokens"]
                    models[m]["out_tokens"] += c["output_tokens"]
                result[tier] = {
                    "count": len(calls),
                    "total_s": round(sum(times), 1),
                    "avg_s": round(sum(times) / len(times), 1),
                    "min_s": round(min(times), 1),
                    "max_s": round(max(times), 1),
                    "total_input_tokens": total_in,
                    "total_output_tokens": total_out,
                    "agents": agents,
                    "models": models,
                    "_raw_calls": calls,  # keep raw data for key distribution analysis
                }
        return result

    def reset(self):
        self._calls = {"reasoning": [], "fast": []}


llm_timing = _LLMTimingTracker()


def reset_all_keys():
    """Reset all key rotation counters. Call at the start of each pipeline run
    to ensure fair key distribution from the beginning.

    Note: OpenRouter reset is commented out intentionally — the cycle continues
    across pipeline runs so we don't always start on the same key.
    """
    # _reset_openrouter_keys()  # Don't reset — let cycle continue across runs
    # _reset_gemini_keys()
    # _reset_groq_keys()
    logger.info("Key rotation counters reset for new pipeline run")


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER: GOOGLE GEMINI (commented out — uncomment to switch back)
# ═══════════════════════════════════════════════════════════════════════════════

# _gemini_key_cycle: itertools.cycle | None = None
# _gemini_key_index: int = 0  # global counter for round-robin tracking
#
# def _next_gemini_key() -> str:
#     global _gemini_key_cycle, _gemini_key_index
#     keys = settings.google_keys
#     if not keys:
#         raise RuntimeError("No GOOGLE_API_KEY configured in .env (need at least GOOGLE_API_KEY_1)")
#     if _gemini_key_cycle is None:
#         _gemini_key_cycle = itertools.cycle(keys)
#     key = next(_gemini_key_cycle)
#     _gemini_key_index += 1
#     return key
#
# def _reset_gemini_keys():
def _get_gemini_llm(model: str, temperature: float = 0.0, api_key: str | None = None,
                    return_key_idx: bool = False, user_id: str | None = None):
    """Create Gemini LLM directly via GOOGLE_API_KEY.

    Args:
        user_id: If provided, use user's Gemini keys before system defaults.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from backend.user_keys import get_effective_keys

    if api_key:
        key = api_key
        key_idx = None
    else:
        keys = get_effective_keys("gemini", user_id)
        if not keys:
            raise RuntimeError("No Gemini API key available (neither user nor system)")
        # Simple round-robin: use first key (could be enhanced with cycle)
        key = keys[0]
        key_idx = 0

    llm = ChatGoogleGenerativeAI(
        model=model, api_key=key,
        temperature=temperature, max_retries=0,
    )
    if return_key_idx:
        return llm, key_idx
    return llm




# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER: OPENROUTER
# ═══════════════════════════════════════════════════════════════════════════════

from langchain_openai import ChatOpenAI
_or_key_cycle: itertools.cycle | None = None
_or_key_index: int = 0  # global counter for round-robin tracking


def _next_openrouter_key(user_id: str | None = None) -> str:
    """Get the next OpenRouter API key in round-robin rotation.

    Args:
        user_id: If provided, try user's keys first before system defaults.
    """
    global _or_key_cycle, _or_key_index
    if _or_key_cycle is None:
        from backend.user_keys import get_effective_keys
        keys = get_effective_keys("openrouter", user_id)
        if not keys:
            raise RuntimeError("No OPENROUTER_KEY available (neither user nor system)")
        _or_key_cycle = itertools.cycle(keys)
    key = next(_or_key_cycle)
    _or_key_index += 1
    return key


def _reset_openrouter_keys():
    """Reset OpenRouter key rotation (call at start of each pipeline run)."""
    global _or_key_cycle, _or_key_index
    _or_key_cycle = None
    _or_key_index = 0


def _get_openrouter_llm(model: str, temperature: float = 0.0, api_key: str | None = None,
                        return_key_idx: bool = False, user_id: str | None = None):
    """Create a ChatOpenAI instance with round-robin key rotation.

    Args:
        return_key_idx: If True, returns (llm, key_index) tuple for tracking.
        user_id: If provided, use user's keys before system defaults.
    """
    if api_key:
        key = api_key
        key_idx = None
    else:
        key = _next_openrouter_key(user_id)
        key_idx = _or_key_index - 1
    if not key:
        raise RuntimeError("No OPENROUTER_KEY available")
    llm = ChatOpenAI(
        model=model, api_key=key,
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature, max_retries=0,  # We handle retries ourselves for better control
        extra_body={
            # OpenRouter prompt caching — caches the system prompt prefix across
            # repeated calls when prefix > 1024 tokens. Saves ~50-80% on input.
            # OpenRouter reads extra_body keys and forwards them appropriately.
            "cache_control": {"type": "ephemeral"},
        },
    )
    if return_key_idx:
        return llm, key_idx
    return llm


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER DISPATCH
# ═══════════════════════════════════════════════════════════════════════════════

def get_llm(model: str, temperature: float = 0.0, api_key: str | None = None,
            return_key_idx: bool = False, user_id: str | None = None,
            base_url: str | None = None):
    """Create an LLM instance based on the model name.

    Auto-detects provider from model name:
      - "gemini-*" → uses Google Gemini (ChatGoogleGenerativeAI)
      - Others → uses OpenAI-compatible format (OpenRouter, Groq, Anthropic, etc.)

    Supports custom base_url + api_key for any provider (user-provided keys).

    Args:
        return_key_idx: If True, returns (llm, key_index) tuple for tracking.
        user_id: If provided, use user's keys before system defaults.
        base_url: Custom base URL (e.g., "https://api.anthropic.com/v1").
    """
    # Auto-detect Gemini models regardless of LLM_PROVIDER setting
    if model.startswith("gemini-"):
        return _get_gemini_llm(model, temperature=temperature, return_key_idx=return_key_idx,
                               user_id=user_id)

    # If custom base_url is provided, use it directly (user-provided key)
    if base_url:
        key = api_key or _next_openrouter_key(user_id)
        key_idx = _or_key_index - 1 if api_key is None else None
        llm = ChatOpenAI(
            model=model, api_key=key,
            base_url=base_url,
            temperature=temperature, max_retries=0,
        )
        if return_key_idx:
            return llm, key_idx
        return llm

    # Otherwise use the configured provider
    provider = settings.llm_provider.lower()
    if provider == "openrouter":
        return _get_openrouter_llm(model, temperature=temperature, api_key=api_key,
                                   return_key_idx=return_key_idx, user_id=user_id)
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER: {provider}. Use 'openrouter'.")


# ── Fallback models per tier ──────────────────────────────────────────────────

# OpenRouter fallbacks (current) — immutable tuples to prevent accidental mutation
_FAST_FALLBACKS = (
    "nvidia/nemotron-nano-9b-v2:free",
    "openai/gpt-oss-20b:free",
    "liquid/lfm-2.5-1.2b-thinking:free",
    "openrouter/free",
)

_REASONING_FALLBACKS = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemini-3.5-flash",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "openrouter/free",
)

# Default LLM call timeout (seconds)
DEFAULT_LLM_TIMEOUT = 120.0

# Groq fallbacks (commented out — uncomment to switch back):
# _FAST_FALLBACKS = [
#     "llama-3.1-8b-instant",
#     "meta-llama/llama-4-scout-17b-16e-instruct",
#     "llama-3.3-70b-versatile",
# ]
# _REASONING_FALLBACKS = [
#     "gemini-3.5-flash",
#     "meta-llama/llama-4-scout-17b-16e-instruct",
#     "llama-3.3-70b-versatile",
#     "gemini-2.5-flash",
# ]


def _get_fallback_models(primary: str, tier: str) -> tuple[str, ...]:
    """Get a tuple of models to try, starting with primary, then fallbacks."""
    fallbacks = _REASONING_FALLBACKS if tier == "reasoning" else _FAST_FALLBACKS
    return (primary,) + tuple(m for m in fallbacks if m != primary)


def _is_server_error(e: Exception) -> bool:
    """Check if error is a 5xx / unavailable / overloaded error."""
    s = str(e)
    sl = s.lower()
    return (
        "503" in s or "500" in s or "502" in s or "504" in s or
        "service unavailable" in sl or
        "internal server error" in sl or
        "overloaded" in sl or
        "unavailable" in sl
    )


# ── Model tier routing ────────────────────────────────────────────────────────

def get_reasoning_llm(user_id: str | None = None):
    """Reasoning-tier agents use model_reasoning (default: gemini-2.5-flash).

    All reasoning agents (Orchestrator, Planner, Synthesizer, Critic) use this.
    When user_id is provided, uses user's keys if available.
    """
    from backend.user_keys import get_effective_model
    model = get_effective_model("openrouter", user_id) or settings.model_reasoning
    return get_llm(model, user_id=user_id)


def get_fast_llm(user_id: str | None = None):
    """Fast/cheap model for Searchers, Browsers, Citation Formatter, FactChecker.

    Uses model_fast (default: nemotron-3-nano via OpenRouter).
    When user_id is provided, uses user's keys if available.
    """
    from backend.user_keys import get_effective_model
    model = get_effective_model("openrouter", user_id) or settings.model_fast
    return get_llm(model, user_id=user_id)


def apply_user_id_to_agent(agent: BaseAgent, config: dict | None):
    """Extract user_id from graph config and set it on the agent.

    Call this in each graph node before using the agent.
    Example: apply_user_id_to_agent(agent, config)
    """
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if user_id:
        agent.set_user_id(user_id)


class BaseAgent:
    """Stateless async agent wrapper around the configured LLM provider."""

    model_tier: str = "fast"  # "reasoning" | "fast"
    system_prompt: str = "You are a helpful research assistant."

    def __init__(self, user_id: str | None = None):
        self._llm = None
        self._user_id = user_id

    @property
    def llm(self):
        if self._llm is None:
            if self.model_tier == "reasoning":
                self._llm = get_reasoning_llm(self._user_id)
            else:
                self._llm = get_fast_llm(self._user_id)
        return self._llm

    def set_user_id(self, user_id: str | None):
        """Set user ID for key resolution. Call before using llm."""
        self._user_id = user_id
        self._llm = None  # Reset cached LLM so next access uses new user_id

    def _get_primary_model(self) -> str:
        if self.model_tier == "reasoning":
            return settings.model_reasoning
        return settings.model_fast

    @observe()
    async def run(
        self,
        user_message: str,
        *,
        system_override: str | None = None,
        tools: Sequence[Callable] = (),
        max_tokens: int = 4096,
        timeout: float = DEFAULT_LLM_TIMEOUT,
    ) -> str:
        """Send a single user message and return the LLM text response.

        Retries with exponential backoff and model fallback on rate-limit errors.
        Records per-call latency for reasoning vs fast tier comparison.
        Raises TimeoutError if all model attempts exceed timeout.
        """
        sys = system_override or self.system_prompt
        messages: list[BaseMessage] = [
            SystemMessage(content=sys),
            HumanMessage(content=user_message),
        ]

        # Update Langfuse span context with dynamic name and explicit clean input
        lf_ctx = get_langfuse_context()
        lf_ctx.update_current_span(
            name=self.__class__.__name__,
            input={"user_message": user_message, "system_prompt": sys}
        )

        primary = self._get_primary_model()
        models_to_try = _get_fallback_models(primary, self.model_tier)

        last_error: Exception | None = None
        n_keys = len(settings.openrouter_keys)

        for model in models_to_try:
            # Try each key for this model before falling back to next model
            for key_attempt in range(n_keys):
                try:
                    # Pick the right LLM constructor based on model name
                    key_idx = None
                    if model.startswith("gemini-"):
                        llm, key_idx = _get_gemini_llm(model, return_key_idx=True)
                    else:
                        llm, key_idx = get_llm(model, return_key_idx=True)
                    if tools:
                        llm = llm.bind_tools(list(tools))
                    
                    # Prepare callbacks for LangChain integration
                    config: dict[str, Any] = {}
                    lf_handler = lf_ctx.get_current_langchain_handler()
                    if lf_handler:
                        config["callbacks"] = [lf_handler]

                    _call_start = time.time()
                    # Gemini uses max_output_tokens; Groq/OpenRouter use max_tokens
                    if model.startswith("gemini-"):
                        config["max_output_tokens"] = max_tokens
                        response = await asyncio.wait_for(
                            llm.ainvoke(messages, config=config),
                            timeout=timeout,
                        )
                    else:
                        response = await asyncio.wait_for(
                            llm.ainvoke(messages, max_tokens=max_tokens, config=config),
                            timeout=timeout,
                        )
                    _latency = time.time() - _call_start
                    # Count tokens in the input messages
                    input_text = "\n".join(str(m.content) for m in messages)
                    input_tokens = llm_timing.count_tokens(input_text)
                    output_text = str(response.content) if response else ""
                    output_tokens = llm_timing.count_tokens(output_text)
                    llm_timing.record(
                        tier=self.model_tier,
                        agent=self.__class__.__name__,
                        model=model,
                        latency_s=_latency,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        key_idx=key_idx,
                    )
                    if model != primary:
                        logger.info(
                            f"Agent {self.__class__.__name__} succeeded with fallback model {model}"
                        )
                    return str(response.content)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    # Treat token-limit (413) as a rate limit so we retry
                    is_rate_limit = (
                        "429" in str(e)
                        or "rate limit" in error_str
                        or "rate-limit" in error_str
                        or "413" in str(e)
                        or "request too large" in error_str
                        or "tokens per minute" in error_str
                    )
                    # Gemini 503 = model unavailable (high demand) — skip to next model immediately
                    is_gemini_unavailable = (
                        "gemini" in model
                        and ("503" in str(e) or "unavailable" in error_str)
                    )
                    if is_gemini_unavailable:
                        # Gemini is overloaded — don't retry keys, fall back to next model
                        logger.warning(
                            f"Gemini unavailable (503) on {model}, falling back to next model..."
                        )
                        break
                    elif is_rate_limit:
                        # Rate limited — try next key for this model
                        logger.warning(
                            f"Rate limited on {model} (key attempt {key_attempt+1}/{n_keys}), trying next key..."
                        )
                        continue
                    else:
                        logger.error(f"LLM error on {model}: {e}")
                        continue
            # All keys exhausted for this model — fall back to next model
            # Each model on OpenRouter has its own 50/day quota, so trying another model is correct
            logger.warning(f"All {n_keys} keys exhausted for {model}, trying next model...")

        raise RuntimeError(f"All LLM attempts failed. Last error: {last_error}")

    @observe()
    async def run_with_messages(
        self,
        messages: list[BaseMessage],
        *,
        tools: Sequence[Callable] = (),
        max_tokens: int = 4096,
        timeout: float = DEFAULT_LLM_TIMEOUT,
    ) -> str:
        """Send a full message list and return the LLM text response.

        Uses the same retry + fallback logic as run().
        """
        # Update Langfuse span context with dynamic name and clean message inputs
        lf_ctx = get_langfuse_context()
        lf_ctx.update_current_span(
            name=f"{self.__class__.__name__}.run_with_messages",
            input={"messages_count": len(messages), "last_message": str(messages[-1].content) if messages else ""}
        )

        primary = self._get_primary_model()
        models_to_try = _get_fallback_models(primary, self.model_tier)

        last_error: Exception | None = None
        n_keys = len(settings.openrouter_keys)

        for model in models_to_try:
            for key_attempt in range(n_keys):
                try:
                    key_idx = None
                    if model.startswith("gemini-"):
                        llm, key_idx = _get_gemini_llm(model, return_key_idx=True)
                    else:
                        llm, key_idx = get_llm(model, return_key_idx=True)
                    if tools:
                        llm = llm.bind_tools(list(tools))

                    # Prepare callbacks for LangChain integration
                    config: dict[str, Any] = {}
                    lf_handler = lf_ctx.get_current_langchain_handler()
                    if lf_handler:
                        config["callbacks"] = [lf_handler]

                    _call_start = time.time()
                    if model.startswith("gemini-"):
                        config["max_output_tokens"] = max_tokens
                        response = await asyncio.wait_for(
                            llm.ainvoke(messages, config=config),
                            timeout=timeout,
                        )
                    else:
                        response = await asyncio.wait_for(
                            llm.ainvoke(messages, max_tokens=max_tokens, config=config),
                            timeout=timeout,
                        )
                    _latency = time.time() - _call_start
                    input_text = "\n".join(str(m.content) for m in messages)
                    input_tokens = llm_timing.count_tokens(input_text)
                    output_text = str(response.content) if response else ""
                    output_tokens = llm_timing.count_tokens(output_text)
                    llm_timing.record(
                        tier=self.model_tier,
                        agent=self.__class__.__name__,
                        model=model,
                        latency_s=_latency,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        key_idx=key_idx,
                    )
                    return str(response.content)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    is_rate_limit = (
                        "429" in str(e)
                        or "rate limit" in error_str
                        or "rate-limit" in error_str
                        or "413" in str(e)
                        or "request too large" in error_str
                        or "tokens per minute" in error_str
                    )
                    is_gemini_unavailable = (
                        "gemini" in model
                        and ("503" in str(e) or "unavailable" in error_str)
                    )
                    if is_gemini_unavailable:
                        logger.warning(f"Gemini unavailable (503) on {model}, falling back to next model...")
                        break
                    elif is_rate_limit:
                        logger.warning(
                            f"Rate limited on {model} (key attempt {key_attempt+1}/{n_keys}), trying next key..."
                        )
                        continue
                    else:
                        logger.error(f"LLM error on {model}: {e}")
                        continue
            logger.warning(f"All keys exhausted for {model}, trying next model...")

        raise RuntimeError(f"All LLM attempts failed in run_with_messages. Last error: {last_error}")
