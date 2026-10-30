# Multi-Stage Production Dockerfile for FraudEngine
# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime Environment with Python 3.10
FROM python:3.10-slim AS runner
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    ALLOW_FULL_PUBLIC_ACCESS="true" \
    DEMO_MODE="true"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt requirements-render.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt -r requirements-render.txt

# Copy application source & models
COPY fraudengine/ ./fraudengine/
COPY configs/ ./configs/
COPY models_v2/ ./models_v2/
COPY results_v2/ ./results_v2/
COPY scripts/ ./scripts/

# Copy built frontend from Stage 1 into frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn fraudengine.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
