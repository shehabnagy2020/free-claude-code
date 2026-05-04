#!/bin/bash
# Startup script for optimized container start
# Pre-warms provider connections and skips unnecessary initialization

set -e

echo "[startup] Starting Claude Code Proxy..."

# Set PATH to include venv
export PATH="/app/.venv/bin:$PATH"

# Pre-warm: Touch provider connection pools (lazy init)
python -c "
from config.settings import settings
print('[startup] Loading settings...')
# Trigger lazy provider initialization
from providers.factory import get_provider
print('[startup] Provider pools initialized')
" 2>/dev/null || true

# Start uvicorn with optimized settings (use python -m to avoid shebang issues)
exec python -m uvicorn server:app \
    --host "0.0.0.0" \
    --port "8082" \
    --timeout-graceful-shutdown 5 \
    --loop uvloop \
    --http httptools
