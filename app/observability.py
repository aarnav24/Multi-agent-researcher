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
from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
        import langfuse
        from langfuse.decorators import langfuse_context
        from langfuse.callback import CallbackHandler

        langfuse.init(
            public_key=public_key,
            secret_key=secret_key,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )

        _langfuse_initialized = True
        logger.info(f"Langfuse: initialized (host={os.getenv('LANGFUSE_HOST', 'cloud')})")
        return True

    except ImportError:
        logger.warning("Langfuse: package not installed")
        return False
    except Exception as e:
        logger.warning(f"Langfuse: init failed: {e}")
        return False


def get_langfuse_handler():
    """Get Langfuse callback handler for LangChain, or None."""
    if not _langfuse_initialized:
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler()
    except Exception as e:
        logger.warning(f"Langfuse: callback handler error: {e}")
        return None


def get_langfuse_context():
    """Get Langfuse context decorator, or passthrough."""
    if not _langfuse_initialized:
        return _PassthroughContext()
    try:
        from langfuse.decorators import langfuse_context
        return langfuse_context
    except Exception:
        return _PassthroughContext()


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
        return None

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
            exporter = OTLPSpanExporter(endpoint=otel_endpoint)
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OpenTelemetry: OTLP exporter → {otel_endpoint}")
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
    @asynccontextmanager
    async def start_as_current_span(self, name, **kwargs):
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
