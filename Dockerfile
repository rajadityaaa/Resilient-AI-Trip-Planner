# ==============================================================================
# Multi-stage Dockerfile for AI Travel Planner Agent
# Default Target: runtime (Slim production FastAPI web service)
# Target 'streamlit': Optional local development compose profile with full UI
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Optional Streamlit Dependency Builder (Full UI dependencies for compose)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS streamlit-builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install-full -r requirements.txt


# ------------------------------------------------------------------------------
# Stage 2: Optional Streamlit Runtime (Invoked via compose profile: `streamlit`)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS streamlit

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY --from=streamlit-builder /install-full /usr/local

RUN groupadd -r appgroup && \
    useradd -r -g appgroup -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appgroup /app

COPY --chown=appuser:appgroup app/ /app/app/

USER appuser

EXPOSE 8501

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]


# ------------------------------------------------------------------------------
# Stage 3: Production Dependency Builder (FastAPI runtime only)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-prod.txt


# ------------------------------------------------------------------------------
# Stage 4: Production Runtime (FINAL / DEFAULT TARGET for Render & Docker)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ENV=production \
    PYTHONPATH=/app

# Copy runtime Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user and ensure writable SQLite data directory
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appgroup /app

# Copy application directory (includes app/web static assets and app/resources/fonts)
COPY --chown=appuser:appgroup app/ /app/app/

USER appuser

EXPOSE 8000

# Health check using stdlib urllib (slim image has no curl)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, os; port = os.getenv('PORT', '8000'); urllib.request.urlopen(f'http://localhost:{port}/health', timeout=4)" || exit 1

# Launch uvicorn via shell to expand ${PORT:-8000} at runtime
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
