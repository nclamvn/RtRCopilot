FROM node:22.14.0-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY patches patches
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

FROM deps AS builder
COPY apps/web apps/web
RUN pnpm --filter @rtr/web build

FROM node:22.14.0-alpine
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /app
RUN addgroup -S app -g 10001 && adduser -S app -u 10001 -G app
COPY --from=builder --chown=app:app /app/apps/web/.next/standalone ./
COPY --from=builder --chown=app:app /app/apps/web/.next/static ./apps/web/.next/static
COPY --chown=app:app infra/docker/web-guard.mjs ./web-guard.mjs
USER app
CMD ["node", "web-guard.mjs"]
