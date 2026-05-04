#!/bin/bash
# Quick restart script for Docker container
# Usage: ./docker-restart.sh [--no-cache]

set -e

echo "=== Restarting claude-code-proxy ==="

if [ "$1" == "--no-cache" ]; then
    echo "Building without cache..."
    docker-compose build --no-cache
else
    echo "Building..."
    docker-compose up -d --build
fi

echo "Waiting for container to be healthy..."
sleep 5

for i in {1..10}; do
    if curl -sf http://localhost:8082/health > /dev/null 2>&1; then
        echo "✓ Container is healthy"
        docker-compose ps
        exit 0
    fi
    echo "  Waiting... ($i/10)"
    sleep 2
done

echo "✗ Container failed to start"
docker-compose logs --tail=20
exit 1
