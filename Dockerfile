# Build Stage
FROM python:3.10-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Default: full requirements.txt (local). Cloud compose overrides with requirements-cloud.txt.
ARG REQUIREMENTS=requirements.txt
COPY ${REQUIREMENTS} requirements.txt
#RUN pip install --upgrade pip && \
#    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Install everything needed for a high-performance ARM build
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

# 3. Build all transitive dependencies into the wheels directory
RUN pip install --upgrade pip setuptools wheel && \
    pip wheel --no-cache-dir \
    --wheel-dir /app/wheels -r requirements.txt

# Final Stage
FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

RUN pip install --no-cache /wheels/*

COPY . .

# Set PYTHONPATH to include the current directory so imports work
ENV PYTHONPATH=/app

# Run as non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck using curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ready || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
