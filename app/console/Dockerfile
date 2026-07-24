# Hub image. The same build runs locally as console/agent; this container is
# the LAB_MODE=hub role only — no python driver, no arm, relay + lobby UI.
FROM oven/bun:1.3.14 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
RUN bun run build

FROM oven/bun:1.3.14
WORKDIR /app
ENV NODE_ENV=production
ENV LAB_MODE=hub
# The server bundle is not self-contained (react/effect/h3 resolved at
# runtime) — ship production node_modules beside dist/.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production
COPY --from=build /app/dist ./dist
CMD ["bun", "dist/server/server.js"]
