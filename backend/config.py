"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM Provider ──────────────────────────────────────────────────────────
    # "openrouter" | "groq"
    llm_provider: str = "openrouter"

    # Groq API keys (3 for round-robin, used when llm_provider == "groq")
    # groq_api_key_1: str = ""
    # groq_api_key_2: str = ""
    # groq_api_key_3: str = ""

    # Model IDs
    # gpt-oss-120b for reasoning agents (planner, orchestrator, critic)
    model_reasoning: str = "gemini-2.5-flash"
    # gemini-2.5-flash for reasoning agents (synthesizer + critic)
    model_synthesizer: str = "gemini-2.5-flash"
    model_fast: str = "nvidia/nemotron-3-nano-30b-a3b:free"

    # Google Gemini (4 keys — immediate model fallback on 503, no key retry)
    google_api_key_1: str = ""
    google_api_key_2: str = ""
    google_api_key_3: str = ""
    google_api_key_4: str = ""
    google_api_key: str = ""  # Deprecated — use the _1/_2/_3/_4 keys
    fact_checker_model: str = "gemini-3.5-flash"

    # OpenRouter keys (8 keys for round-robin)
    openrouter_key_1: str = ""
    openrouter_key_2: str = ""
    openrouter_key_3: str = ""
    openrouter_key_4: str = ""
    openrouter_key_5: str = ""
    openrouter_key_6: str = ""
    openrouter_key_7: str = ""
    openrouter_key_8: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 20

    # Postgres
    database_url: str = "postgresql+asyncpg://swarm:swarm@localhost:5432/deep_research"
    postgres_min_pool: int = 2
    postgres_max_pool: int = 10

    # Neo4j (Citation Graph — Layer C)
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "deep_research_2026"
    neo4j_database: str = "neo4j"

    # Search API keys
    tavily_api_key: str = ""  # Deprecated — use _1/_2/_3/_4/_5
    tavily_api_key_1: str = ""
    tavily_api_key_2: str = ""
    tavily_api_key_3: str = ""
    tavily_api_key_4: str = ""
    tavily_api_key_5: str = ""
    serpapi_api_key: str = ""
    exa_api_key: str = ""
    github_token: str = ""

    # Firebase (backend / Admin SDK — server-side only)
    firebase_api_key: str = ""
    firebase_project_id: str = ""
    firebase_client_email: str = ""
    firebase_private_key: str = ""

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Search backend: "exa" | "ddg"
    search_backend: str = "exa"

    # Kill switches
    max_concurrent_agents: int = 10
    max_tool_calls_per_agent: int = 8
    max_agent_invocations: int = 30
    max_critic_rounds: int = 2

    # Browser worker pool (separate from searcher concurrency for I/O-bound fetching)
    max_browser_workers: int = 4

    @property
    def openrouter_keys(self) -> list[str]:
        keys = [self.openrouter_key_1, self.openrouter_key_2, self.openrouter_key_3,
                self.openrouter_key_4, self.openrouter_key_5, self.openrouter_key_6,
                self.openrouter_key_7, self.openrouter_key_8]
        return [k for k in keys if k]

    @property
    def groq_keys(self) -> list[str]:
        keys = [self.groq_api_key_1, self.groq_api_key_2, self.groq_api_key_3]
        return [k for k in keys if k]

    @property
    def google_keys(self) -> list[str]:
        keys = [self.google_api_key_1, self.google_api_key_2, self.google_api_key_3,
                self.google_api_key_4]
        # Fallback to deprecated single key if 4-key rotation not configured
        if not any(keys) and self.google_api_key:
            keys = [self.google_api_key]
        return [k for k in keys if k]

    @property
    def tavily_keys(self) -> list[str]:
        keys = [self.tavily_api_key_1, self.tavily_api_key_2, self.tavily_api_key_3,
                self.tavily_api_key_4, self.tavily_api_key_5]
        # Fallback to deprecated single key if 5-key rotation not configured
        if not any(keys) and self.tavily_api_key:
            keys = [self.tavily_api_key]
        return [k for k in keys if k]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Allow extra env vars (frontend/observability) without crashing


settings = Settings()
