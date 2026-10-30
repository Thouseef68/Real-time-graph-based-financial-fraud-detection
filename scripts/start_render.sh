#!/usr/bin/env bash
# scripts/start_render.sh
# Production Start Script for Render.com

set -e

PORT_TO_USE="${PORT:-8000}"
echo "=== Starting FraudEngine Unified Platform on port ${PORT_TO_USE} ==="
exec python -m uvicorn fraudengine.api.app:app --host 0.0.0.0 --port "${PORT_TO_USE}"
