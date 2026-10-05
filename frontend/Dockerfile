# Install dependencies in a separate stage so the final image is small.
FROM node:20-alpine AS dependencies
WORKDIR /app
COPY package*.json ./
# The dashboard image does not need the Cypress browser binary; e2e runs on
# the host or a separate test image.
ENV CYPRESS_INSTALL_BINARY=0
RUN npm ci

# Build the optimized Next.js standalone server.
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ARG NEXT_PUBLIC_DEMO=0
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_DEMO=${NEXT_PUBLIC_DEMO}
RUN npm run build

# Only the standalone output and static assets are needed at runtime.
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
