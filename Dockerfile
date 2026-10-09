# LAKO — hosted build (Render). FastAPI backend + built React frontend in one service.

FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY config/ config/
COPY LAKO_Postman_Collection.json ./
COPY --from=frontend /build/dist frontend/dist
COPY docker-entrypoint.sh ./
ENTRYPOINT ["./docker-entrypoint.sh"]
