# Frontend static build — produces /app/out/ for Caddy to serve
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV NEXT_OUTPUT_EXPORT=true
# Absorb any NEXT_PUBLIC_API_BASE_URL passed from the host/compose env,
# then immediately override it to empty string. This ensures Caddy's
# /api/* proxy is always used (relative paths), preventing Mixed Content
# errors when the cloud .env has an http:// URL baked in.
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=""
RUN npm run build

# Minimal image to hold the static files (copied out via Docker volume)
FROM alpine:3.19
# Stage to /build-output so the volume mount at /srv/frontend doesn't shadow new files
COPY --from=builder /app/out /build-output
