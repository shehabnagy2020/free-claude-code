# Multi-stage Dockerfile for Claude Code Proxy
# Supports all providers: NVIDIA NIM, OpenRouter, DeepSeek, Google Gemini, LM Studio, Llama.cpp, Ollama

# ==================== Builder Stage ====================
FROM python:3.14-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Copy project files
COPY pyproject.toml uv.lock ./
COPY api/ ./api/
COPY cli/ ./cli/
COPY config/ ./config/
COPY core/ ./core/
COPY messaging/ ./messaging/
COPY providers/ ./providers/

# Install dependencies into a virtual environment
ENV UV_PROJECT_ENVIRONMENT=/build/.venv
RUN /root/.local/bin/uv sync --frozen

# Install Node.js for context-mode sidecar (optional)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js dependencies for context-mode
COPY package.json ./
RUN npm install --ignore-scripts

# Build the UI
COPY ui/ ./ui/
RUN cd ui && npx vite build

# ==================== Runtime Stage ====================
FROM python:3.14-slim AS runtime

LABEL maintainer="free-claude-code"
LABEL description="Claude Code Proxy - Multi-provider middleware"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js runtime for context-mode sidecar (optional)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/node_modules /app/node_modules

# Copy application code
COPY --from=builder /build/api /app/api
COPY --from=builder /build/cli /app/cli
COPY --from=builder /build/config /app/config
COPY --from=builder /build/core /app/core
COPY --from=builder /build/messaging /app/messaging
COPY --from=builder /build/providers /app/providers
COPY --from=builder /build/server.py /app/
COPY --from=builder /build/package.json /app/

# Copy built UI
COPY --from=builder /build/ui/dist /app/ui/dist

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOST=0.0.0.0
ENV PORT=8082

# Expose the server port
EXPOSE 8082

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8082/health || exit 1

# Default command - runs the FastAPI server via uvicorn
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8082", "--timeout-graceful-shutdown", "5"]

# ==================== Development Stage ====================
FROM runtime AS development

USER root
RUN chown -R appuser:appuser /app
USER appuser

# Mount .venv as a volume for development
VOLUME /app

# Override entrypoint for development
ENTRYPOINT []
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8082", "--reload", "--timeout-graceful-shutdown", "5"]
