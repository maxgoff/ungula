# Stage 1: Build frontend
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Install Python dependencies
FROM python:3.11-slim AS python-build
WORKDIR /build
COPY backend/pyproject.toml backend/README.md ./
COPY backend/ungula/ ./ungula/
RUN pip install --no-cache-dir --prefix=/install .

# Stage 3: Final image
FROM python:3.11-slim

# Create non-root user
RUN groupadd -r ungula && useradd -r -g ungula -m ungula

# Copy installed Python packages and CLI
COPY --from=python-build /install /usr/local

# Copy application source
WORKDIR /app
COPY backend/ungula/ ./ungula/

# Copy frontend dist
COPY --from=frontend-build /build/dist ./frontend/dist

# Data volume
ENV UNGULA_HOME=/data
VOLUME ["/data"]

# Switch to non-root user
USER ungula

EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8001/api/health', timeout=5); r.raise_for_status()" || exit 1

CMD ["ungula", "start"]
