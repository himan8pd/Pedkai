# syntax=docker/dockerfile:1
# Build Stage
FROM python:3.10-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Single consolidated apt-get for all build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    python3-dev \
    cmake \
    ninja-build \
    git \
    && rm -rf /var/lib/apt/lists/*

# Crucial: Tell CMake exactly where to find the compilers
ENV CC=/usr/bin/gcc
ENV CXX=/usr/bin/g++
ENV CMAKE_CXX_COMPILER=/usr/bin/g++
ENV CMAKE_C_COMPILER=/usr/bin/gcc
ENV CMAKE_GENERATOR=Ninja

# Default: full requirements.txt (local). Cloud compose overrides with requirements-cloud.txt.
ARG REQUIREMENTS=requirements.txt
COPY ${REQUIREMENTS} requirements.txt

# Build wheels with BuildKit cache mount — pip's download/build cache persists
# across builds even when the layer is invalidated by requirements changes.
# This cuts ARM wheel compilation from ~10 min to ~1 min on repeat builds.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip wheel --wheel-dir /app/wheels -r requirements.txt

# Final Stage
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/requirements.txt .

# Install from builder's wheels without copying them into this image's layers.
# --mount=type=bind makes /wheels available during this RUN only — no layer created.
# Nvidia CUDA packages are stripped afterwards: ARM is CPU-only, they're pure waste (~1.7GB).
RUN --mount=type=bind,from=builder,source=/app/wheels,target=/wheels \
    --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /wheels/* && \
    pip install --no-cache-dir "tokenizers>=0.20,<0.22" && \
    sed -i 's|"tokenizers>=0.19,<0.20"|"tokenizers>=0.19"|' \
        /usr/local/lib/python3.10/site-packages/transformers/dependency_versions_table.py && \
    rm -rf /usr/local/lib/python3.10/site-packages/nvidia

COPY . .

# Set PYTHONPATH to include the current directory so imports work
ENV PYTHONPATH=/app

# Run as non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
# Pre-create HuggingFace cache dir so the named hf_cache volume inherits
# appuser ownership on first mount. Without this, the volume root is owned
# by root and the T-VEC model download fails with EACCES.
RUN mkdir -p /home/appuser/.cache/huggingface && chown -R appuser:appuser /home/appuser/.cache
USER appuser

EXPOSE 8000

# Healthcheck using curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ready || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
