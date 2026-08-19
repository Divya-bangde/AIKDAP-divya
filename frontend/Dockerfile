# AIKDAP frontend image.
#
# Not wired into docker-compose.yml (Sprint 9K's approved design keeps
# the existing four-service setup unchanged) -- this exists so the
# frontend has a working container path when it is added later,
# without waiting on a future sprint to write it from scratch.
# Local development uses `npm run dev`, not this image.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
