# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 - compile the React/TypeScript dashboard
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Everything else is copied after the dependency layer so rebuilds are fast.
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 - Python runtime serving the API *and* the compiled SPA
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    STORAGE_DIR=/app/storage \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

# libgl1 / libglib are required by OpenCV (used for the demo renderer and
# JPEG encoding even when no real camera is attached).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY backend ./backend
COPY --from=frontend /build/dist ./frontend/dist

RUN mkdir -p /app/storage/snapshots /app/storage/clips /app/storage/faces /app/storage/exports /app/storage/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api', timeout=4)"

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
