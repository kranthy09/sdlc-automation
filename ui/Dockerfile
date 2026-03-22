# Enterprise AI UI — Vite React dev server
# Build: docker build -t enterprise-ai-ui ./ui
# Run:   docker compose -f infra/docker/docker-compose.dev.yaml up ui

FROM node:20-alpine

WORKDIR /app

# Install dependencies (layer-cached)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source
COPY . .

EXPOSE 5173

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:5173 || exit 1

# Run vite directly (avoids CJS crypto issue with --experimental-global-webcrypto on Node 20)
CMD ["node_modules/.bin/vite", "--host", "0.0.0.0"]
