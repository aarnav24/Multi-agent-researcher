"""Observability — Langfuse (LLM tracing) + OpenTelemetry (system traces).

Langfuse tracks:
  - Every LLM call (input, output, latency, tokens, model, cost)
  - Agent execution spans (searcher, browser, fact-checker, critic, etc.)
  - Full research session traces (end-to-end pipeline)

OpenTelemetry traces:
  - FastAPI HTTP requests
  - Postgres queries (asyncpg)
  - Custom spans for graph node execution

Environment variables:
  LANGFUSE_PUBLIC_KEY=...
  LANGFUSE_SECRET_KEY=...
  LANGFUSE_HOST=https://cloud.langfuse.com  (self-hosted: http://localhost:3001)
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces  (or Langfuse)
  OTEL_SERVICE_NAME=deep-research-swarm
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator
from dotenv import load_dotenv

# Load environment variables from .env in workspace root
load_dotenv()

logger = logging.getLogger(__name__)

# ── Langfuse ────────────────────────────────────────────────────────────

_langfuse_initialized = False


def init_langfuse() -> bool:
    """Initialize Langfuse decorators/context. Returns True if enabled."""
    global _langfuse_initialized

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        logger.info("Langfuse: not configured (LANGFUSE_PUBLIC_KEY/SECRET_KEY not set)")
        return False

    try:
        from langfuse import observe, get_client
        # Instantiate client to validate keys/host
        client = get_client()
        _langfuse_initialized = True
        logger.info(f"Langfuse: initialized (host={os.getenv('LANGFUSE_HOST', 'cloud')})")
        return True
    except ImportError as e:
        logger.warning(f"Langfuse: package not installed or import error: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.warning(f"Langfuse: init failed: {e}")
        return False


def get_langfuse_handler():
    """Get Langfuse callback handler for LangChain, or None."""
    if not _langfuse_initialized:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as e:
        logger.warning(f"Langfuse: callback handler error: {e}")
        return None


class LangfuseContextWrapper:
    """Helper to mimic old langfuse_context with OTEL backend in Langfuse v4."""

    def __init__(self):
        from langfuse import get_client
        self.client = get_client()

    @contextmanager
    def trace(self, *, name, input=None, session_id=None, user_id=None, metadata=None, **kwargs):
        from langfuse import propagate_attributes
        with propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
        ):
            with self.client.start_as_current_observation(
                name=name,
                as_type="span",
                input=input,
            ) as obs:
                yield obs

    @staticmethod
    def get_current_langchain_handler():
        try:
            from langfuse.langchain import CallbackHandler
            return CallbackHandler()
        except Exception:
            return None

    @staticmethod
    def update_current_span(*args, **kwargs):
        try:
            from langfuse import get_client
            get_client().update_current_span(*args, **kwargs)
        except Exception:
            pass

    @staticmethod
    def update_current_trace(*args, **kwargs):
        pass

    @staticmethod
    def score(*args, **kwargs):
        try:
            from langfuse import get_client
            get_client().create_score(*args, **kwargs)
        except Exception:
            pass

    @staticmethod
    def flush():
        try:
            from langfuse import get_client
            get_client().flush()
        except Exception:
            pass


def get_langfuse_context():
    """Get Langfuse context decorator, or passthrough."""
    if not _langfuse_initialized:
        return _PassthroughContext()
    return LangfuseContextWrapper()


def observe(*args, **kwargs):
    """Langfuse observe decorator or no-op fallback."""
    if not _langfuse_initialized:
        def decorator(f):
            return f
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator
    try:
        from langfuse import observe as lf_observe
        return lf_observe(*args, **kwargs)
    except Exception:
        def decorator(f):
            return f
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


class _PassthroughContext:
    """No-op context when Langfuse is disabled."""

    @staticmethod
    def observe(fn=None, *, name=None):
        if fn:
            return fn
        def decorator(f):
            return f
        return decorator

    @staticmethod
    def trace(**kwargs):
        """Return a no-op sync context manager (used via `with lf_ctx.trace(...)`)."""
        import contextlib
        return contextlib.contextmanager(lambda: (yield))()

    @staticmethod
    def get_current_langchain_handler():
        return None

    @staticmethod
    def update_current_span(*args, **kwargs):
        pass

    @staticmethod
    def update_current_trace(*args, **kwargs):
        pass

    @staticmethod
    def score(*args, **kwargs):
        pass

    @staticmethod
    def flush():
        pass


# ── OpenTelemetry ────────────────────────────────────────────────────────

_otel_initialized = False


def init_opentelemetry() -> bool:
    """Initialize OpenTelemetry tracing. Returns True if enabled."""
    global _otel_initialized

    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    # If Langfuse is configured but the OTEL exporter is targeting localhost/127.0.0.1 (which fails inside docker)
    # or is not configured, direct OTEL traces to Langfuse's public OTEL ingestion endpoint.
    if public_key and secret_key:
        if not otel_endpoint or "localhost" in otel_endpoint or "127.0.0.1" in otel_endpoint:
            langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
            if "us.cloud.langfuse.com" in langfuse_host:
                otel_endpoint = "https://us.api.tool.langfuse.com/v1/otel"
            elif "cloud.langfuse.com" in langfuse_host:
                otel_endpoint = "https://api.tool.langfuse.com/v1/otel"
            else:
                # Self-hosted Langfuse OTEL endpoint format
                otel_endpoint = f"{langfuse_host}/api/public/otel"

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "deep-research-swarm"),
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })

        tracer_provider = TracerProvider(resource=resource)

        if otel_endpoint:
            headers = {}
            if public_key and secret_key:
                import base64
                auth_str = f"{public_key}:{secret_key}"
                auth_b64 = base64.b64encode(auth_str.encode()).decode()
                headers["Authorization"] = f"Basic {auth_b64}"

            exporter = OTLPSpanExporter(endpoint=otel_endpoint, headers=headers)
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OpenTelemetry: OTLP exporter → {otel_endpoint} (auth headers configured)")
        else:
            # No exporter configured — traces are collected but not exported
            # Still useful for Langfuse (which reads OTEL traces directly)
            logger.info("OpenTelemetry: no OTLP endpoint, traces collected for Langfuse")

        trace.set_tracer_provider(tracer_provider)

        _otel_initialized = True
        logger.info("OpenTelemetry: initialized")
        return True

    except ImportError:
        logger.warning("OpenTelemetry: package not installed")
        return False
    except Exception as e:
        logger.warning(f"OpenTelemetry: init failed: {e}")
        return False


def get_tracer():
    """Get OpenTelemetry tracer, or no-op."""
    if not _otel_initialized:
        return _NoOpTracer()
    from opentelemetry import trace
    return trace.get_tracer("deep-research-swarm")


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield _NoOpSpan()


class _NoOpSpan:
    def set_attribute(self, key, value):
        pass

    def record_exception(self, exception, **kwargs):
        pass

    def set_status(self, status, **kwargs):
        pass


# ── FastAPI Instrumentation ─────────────────────────────────────────────

def instrument_fastapi(app):
    """Instrument FastAPI app with OpenTelemetry."""
    if not _otel_initialized:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry: FastAPI instrumented")
    except ImportError:
        logger.warning("OpenTelemetry FastAPI instrumentation not available")
    except Exception as e:
        logger.warning(f"OpenTelemetry FastAPI instrumentation failed: {e}")


def instrument_asyncpg():
    """Instrument asyncpg for OpenTelemetry."""
    if not _otel_initialized:
        return
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        AsyncPGInstrumentor().instrument()
        logger.info("OpenTelemetry: asyncpg instrumented")
    except ImportError:
        logger.warning("OpenTelemetry asyncpg instrumentation not available")
    except Exception as e:
        logger.warning(f"OpenTelemetry asyncpg instrumentation failed: {e}")


# ── Combined Init ──────────────────────────────────────────────────────

@asynccontextmanager
async def observability_lifespan(app) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context — init observability on startup, flush on shutdown."""
    init_langfuse()
    init_opentelemetry()
    instrument_fastapi(app)
    instrument_asyncpg()
    yield
    # Flush on shutdown
    if _langfuse_initialized:
        try:
            import langfuse
            langfuse.flush()
        except Exception:
            pass
