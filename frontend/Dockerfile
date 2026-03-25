# Frontend static build — produces /app/out/ for Caddy to serve
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV NEXT_OUTPUT_EXPORT=true
# Force relative API paths: Caddy proxies /api/* to the backend.
# An empty string here ensures any value in .env on the host is NOT
# baked into the static bundle (which would cause a Mixed Content error
# when pedk.ai is served over HTTPS but the .env has http://... URL).
ENV NEXT_PUBLIC_API_BASE_URL=""
RUN npm run build

# Minimal image to hold the static files (copied out via Docker volume)
FROM alpine:3.19
# Stage to /build-output so the volume mount at /srv/frontend doesn't shadow new files
COPY --from=builder /app/out /build-output
