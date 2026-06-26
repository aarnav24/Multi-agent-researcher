FROM python:3.12-slim AS base

WORKDIR /app

# Install system deps for Playwright
RUN apt-get update && apt-get install -y \
    gnupg2 curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY app/ app/

RUN playwright install chromium
RUN playwright install-deps chromium

# ── Production stage ────────────────────────────────────────────────────
FROM base AS production

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
