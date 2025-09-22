# Frontend Dockerfile (build then export to volume for nginx)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# Final stage is omitted in favor of nginx service mounting the build via volume
FROM busybox:1.36
WORKDIR /dist
COPY --from=build /app/dist ./
CMD ["sh", "-c", "echo Built. This image is just a dummy; nginx mounts the dist via a volume."]
