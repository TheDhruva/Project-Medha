# MEDHA single-service image: FastAPI backend + Next.js frontend, one origin.
# Render builds this with `runtime: docker` (see render.yaml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Node.js 20 for the Next.js frontend build and runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

WORKDIR /app

# Backend dependencies first (better layer caching).
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Backend source (evaluation artifacts and local DBs excluded via .dockerignore;
# the database is created fresh at startup by init_db).
COPY backend ./backend

# Frontend: reproducible install, then production build. No NEXT_PUBLIC_*
# values are required at build time: the browser uses same-origin relative
# URLs and Next.js rewrites proxy /api/* and /health to the backend.
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY frontend ./frontend
RUN cd frontend && npm run build \
    && npm prune --omit=dev --no-audit --no-fund

COPY scripts ./scripts

# Run as a non-root user: the hosted demo clones/arbitrary-repo content is
# untrusted input, so the container should not be root even though no Docker
# socket or privileged capability exists inside it.
RUN useradd -m -s /bin/bash appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /var/medha-data \
    && chown appuser:appuser /var/medha-data
USER appuser

# Production defaults (Render envVars may override; MEDHA_API_TOKEN and PORT
# are always provided by the platform configuration, never baked in here).
ENV MEDHA_ENV=production \
    MEDHA_DEBUG=false \
    NEXT_TELEMETRY_DISABLED=1 \
    MEDHA_HOST=127.0.0.1 \
    MEDHA_BACKEND_HOST=127.0.0.1 \
    MEDHA_BACKEND_PORT=8000 \
    MEDHA_EXECUTOR_MODE=disabled \
    MEDHA_DOCKER_EXECUTE=false \
    MEDHA_DATABASE_PATH=/var/medha-data/medha.db \
    MEDHA_LOG_LEVEL=INFO

EXPOSE 10000

CMD ["python", "scripts/run_service.py"]
