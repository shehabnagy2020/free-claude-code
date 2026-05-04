# Multi-stage Dockerfile for Claude Code Proxy
# Supports all providers: NVIDIA NIM, OpenRouter, DeepSeek, Google Gemini, LM Studio, Llama.cpp, Ollama

# ==================== Builder Stage ====================
FROM python:3.14-slim AS builder

WORKDIR /build

# Install uv for fast Python package management
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dependencies (non-editable)
COPY pyproject.toml uv.lock README.md .env.example ./
ENV UV_PROJECT_ENVIRONMENT=/build/.venv
RUN /root/.local/bin/uv sync --frozen --no-editable

# Copy application code
COPY api/ ./api/
COPY cli/ ./cli/
COPY config/ ./config/
COPY core/ ./core/
COPY messaging/ ./messaging/
COPY providers/ ./providers/
COPY server.py ./

# ==================== Runtime Stage ====================
FROM python:3.14-slim AS runtime

LABEL maintainer="free-claude-code"
LABEL description="Claude Code Proxy - Multi-provider middleware"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application code
COPY --from=builder /build/api /app/api
COPY --from=builder /build/cli /app/cli
COPY --from=builder /build/config /app/config
COPY --from=builder /build/core /app/core
COPY --from=builder /build/messaging /app/messaging
COPY --from=builder /build/providers /app/providers
COPY --from=builder /build/server.py /app/

# Copy pre-built UI
COPY ui/dist /app/ui/dist
COPY package.json /app/

# Copy startup optimization script
COPY startup.sh /app/startup.sh
RUN chmod +x /app/startup.sh

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOST=0.0.0.0
ENV PORT=8082

EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8082/health || exit 1

# Use optimized startup script
CMD ["/app/startup.sh"]
