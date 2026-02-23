# ── Stage 1: Build React frontend ───────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python server ────────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# Install server dependencies first (layer caches on code changes)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Install the package
COPY pyproject.toml .
COPY sift/ ./sift/
COPY server/ ./server/
RUN pip install --no-cache-dir -e .

# Copy built frontend from stage 1
COPY --from=frontend /frontend/dist ./frontend/dist

# /data is the persistent volume — mount your appdata path here
# SIFT_DB_PATH and SIFT_CONFIG_PATH both point into /data
VOLUME ["/data"]
ENV SIFT_DB_PATH=/data/sift.duckdb
ENV SIFT_CONFIG_PATH=/data/sift.config

EXPOSE 8765

CMD ["uvicorn", "server.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--log-level", "info"]
