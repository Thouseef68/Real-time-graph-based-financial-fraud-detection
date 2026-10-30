#!/usr/bin/env bash
# scripts/build_render.sh
# Production Build Script for Render.com Free Web Service

set -e

echo "=== [1/3] Building React Frontend SPA ==="
cd frontend
npm install --include=dev
npm run build
cd ..

echo "=== [2/3] Installing Python Dependencies ==="
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt -r requirements-render.txt

echo "=== [3/3] Build Completed Successfully ==="
