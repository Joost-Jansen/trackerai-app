# health-web (Next.js): the health-tracker site; health-api answers /api/* behind it.
#
# Build context is the repo root (`docker build -f health-tracker/web/Dockerfile .`), for the npm workspace and packages/.
# Multi-stage: `output: "standalone"` emits .next/standalone with only the modules actually imported, plus server.js.
FROM node:26-alpine AS deps
WORKDIR /repo
# The whole workspace's manifests: npm ci needs every workspace the lockfile names.
COPY package.json package-lock.json ./
COPY health-tracker/web/package.json health-tracker/web/
COPY wealth-tracker/frontend/package.json wealth-tracker/frontend/
COPY trackerai/web/package.json trackerai/web/
COPY packages/ packages/
RUN npm ci

FROM deps AS builder
WORKDIR /repo/health-tracker/web
COPY health-tracker/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# Where /api/* goes (health-api). Next fixes it in rewrites() during the build, so it is a build argument.
ARG API_INTERNAL_URL
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
RUN npm run build

FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S -u 1001 -G nodejs nextjs

# The standalone server is laid out like the repo (outputFileTracingRoot); the static assets go next to it.
COPY --from=builder --chown=nextjs:nodejs /repo/health-tracker/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/health-tracker/web/.next/static ./health-tracker/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /repo/health-tracker/web/public ./health-tracker/web/public

USER nextjs
EXPOSE 3000

# PORT can be changed at run time (Railway sets it), so the check reads it too.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:'+(process.env.PORT||3000)+'/login/',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "health-tracker/web/server.js"]
