# Clarus ERP — one image: the React screens are built, then served by the FastAPI backend.

# --- 1. frontend build ---
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# "" = the screens call the API on their own address. Google Picker settings come from build args.
ARG VITE_GOOGLE_CLIENT_ID=""
ARG VITE_GOOGLE_API_KEY=""
ARG VITE_GOOGLE_APP_ID=""
ENV VITE_API_BASE_URL="" \
    VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID \
    VITE_GOOGLE_API_KEY=$VITE_GOOGLE_API_KEY \
    VITE_GOOGLE_APP_ID=$VITE_GOOGLE_APP_ID
RUN npm run build

# --- 2. backend ---
FROM python:3.11-slim
# pg_dump / pg_restore 18 (same as the database), fonts for the PDFs
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg fonts-dejavu-core \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
ENV APP_ENV=production PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/frontend/dist \
    DOCUMENT_STORAGE_ROOT=/tmp/erp-storage/documents BACKUP_DIR=/tmp/erp-backups
RUN useradd --create-home erp && chown -R erp /app
USER erp
EXPOSE 8080
HEALTHCHECK CMD curl -fsS "http://localhost:${PORT:-8080}/health" || exit 1
CMD ["scripts/start.sh"]
