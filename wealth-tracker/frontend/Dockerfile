# Stock Tracker web (Next.js) container image.
#
# Build context is the repo root (`docker build -f wealth-tracker/frontend/Dockerfile .`),
# for the npm workspace and packages/.
#
# Multi-stage so the runtime image carries neither the build toolchain nor
# the full node_modules tree: next.config.js sets `output: "standalone"`,
# which emits .next/standalone with only the modules actually imported,
# plus a self-contained server.js.
FROM node:22-alpine AS deps
WORKDIR /repo
# The whole workspace's manifests: npm ci needs every workspace the lockfile names.
COPY package.json package-lock.json ./
COPY health-tracker/web/package.json health-tracker/web/
COPY wealth-tracker/frontend/package.json wealth-tracker/frontend/
COPY trackerai/web/package.json trackerai/web/
COPY packages/ packages/
RUN npm ci

FROM deps AS builder
WORKDIR /repo/wealth-tracker/frontend
COPY wealth-tracker/frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# Where /api/* goes. Next reads this in rewrites() during the build and fixes it
# there, so it has to be a build argument; a runtime variable comes too late.
# Behind Caddy (the Pi) it does not matter, because Caddy forwards /api/*
# itself. On Railway it does: there this rewrite is the only way to the API.
ARG API_INTERNAL_URL
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S -u 1001 -G nodejs nextjs

# standalone bundles server.js + its node_modules, laid out like the repo
# (outputFileTracingRoot); static assets are not included in it and must be
# copied alongside, at the path server.js expects.
COPY --from=builder --chown=nextjs:nodejs /repo/wealth-tracker/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/wealth-tracker/frontend/.next/static ./wealth-tracker/frontend/.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/login',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "wealth-tracker/frontend/server.js"]
