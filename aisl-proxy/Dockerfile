# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1: dependencies (cached independently of source changes)
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# The optional `proxy_ca` build secret lets the image build behind a
# TLS-inspecting egress proxy without baking a corporate CA into the runtime
# image. Without the secret the mount is empty and this is a plain `npm ci`:
#   docker build --secret id=proxy_ca,src=/path/to/ca-bundle.crt .
RUN --mount=type=secret,id=proxy_ca,target=/tmp/proxy-ca.crt \
    if [ -s /tmp/proxy-ca.crt ]; then export NODE_EXTRA_CA_CERTS=/tmp/proxy-ca.crt; fi; \
    npm ci --no-audit --no-fund

# ---------------------------------------------------------------------------
# Stage 2: build — compile TypeScript, then prune to production dependencies
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json tsconfig.json tsconfig.build.json ./
COPY scripts ./scripts
COPY src ./src
RUN npm run build && npm prune --omit=dev

# ---------------------------------------------------------------------------
# Stage 3: runtime — no compiler, no dev dependencies, unprivileged user
# ---------------------------------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    PORT=8080 \
    HOST=0.0.0.0 \
    NODE_OPTIONS=--enable-source-maps

# `node` (uid 1000) ships with the base image; running as root would let a
# gateway compromise write to the image filesystem.
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --chown=node:node package.json ./

USER node
EXPOSE 8080

# The readiness probe checks Postgres and Redis, so an unhealthy dependency
# takes the container out of rotation instead of black-holing checkouts.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||8080)+'/ready').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
