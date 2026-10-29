# tabstealth-web (Next.js): the tabstealth site; tabstealth-api answers /api/* behind it.
#
# Build context is the repo root (`docker build -f tabstealth/web/Dockerfile .`), for the npm workspace and packages/.
# Multi-stage: `output: "standalone"` emits .next/standalone with only the modules actually imported, plus server.js.
FROM node:22-alpine AS deps
WORKDIR /repo
# The whole workspace's manifests: npm ci needs every workspace the lockfile names.
COPY package.json package-lock.json ./
COPY tabstealth/web/package.json tabstealth/web/
COPY health-tracker/web/package.json health-tracker/web/
COPY wealth-tracker/frontend/package.json wealth-tracker/frontend/
COPY trackerai/web/package.json trackerai/web/
COPY packages/ packages/
RUN npm ci

FROM deps AS builder
WORKDIR /repo/tabstealth/web
COPY tabstealth/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
# Where /api/* goes (tabstealth-api). Next fixes it in rewrites() during the build, so it is a build argument.
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

# The standalone server is laid out like the repo (outputFileTracingRoot); the static assets go next to it.
COPY --from=builder --chown=nextjs:nodejs /repo/tabstealth/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/tabstealth/web/.next/static ./tabstealth/web/.next/static

USER nextjs
EXPOSE 3000

# PORT can be changed at run time (Railway sets it), so the check reads it too.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:'+(process.env.PORT||3000)+'/login/',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "tabstealth/web/server.js"]
