# Voice AI Receptionist — production image
# Runs FastAPI + Pipecat pipeline on Render free tier (0.1 vCPU, 512MB RAM).
# Uses uv for reproducible installs from uv.lock.

FROM python:3.12-slim AS base

WORKDIR /app

# Install uv — matches local dev toolchain, resolves from uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for Docker layer caching —
# only re-installs when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# Copy application code (tests/scripts excluded via .dockerignore)
COPY src/ src/

# Render injects PORT env var (typically 10000).
# Default to 10000 if not set.
ENV PORT=10000
EXPOSE ${PORT}

# Shell form so ${PORT} is expanded at runtime.
# No --reload in production.
CMD ["sh", "-c", "uv run uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
