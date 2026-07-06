# Project Meridian frontend image.
# Stage 1 builds the SPA with Node; stage 2 serves static files with Nginx.
# The runtime image contains no source code or Node dev dependencies.
#
# Build with the repository root as context so the Nginx config under
# deploy/nginx is reachable:
#   docker build -f frontend/Dockerfile -t meridian-frontend .

# --- Build -----------------------------------------------------------------
FROM node:24-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- Runtime ---------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
