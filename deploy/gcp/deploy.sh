#!/usr/bin/env bash
# Release a new version: build -> back up + migrate (Cloud Run Job) -> deploy.  Run in Cloud Shell:
#   cd ~/clarus-erp && git pull && bash deploy/gcp/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null
TAG="$IMAGE:$(git rev-parse --short HEAD)"
API_KEY=$(gcloud secrets versions access latest --secret=vite-google-api-key)

TAG="${TAG_OVERRIDE:-$TAG}"
echo "== 1/3 build $TAG"
[ "${SKIP_BUILD:-0}" = "1" ] && echo "(already built)" || gcloud builds submit --config deploy/gcp/cloudbuild.yaml --region "$REGION" \
  --substitutions "_IMAGE=$TAG,_VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID,_VITE_GOOGLE_API_KEY=$API_KEY,_VITE_GOOGLE_APP_ID=$VITE_GOOGLE_APP_ID" .

ENV="APP_ENV=production,AUTO_MIGRATE=0,JOBS_ENABLED=0,STORAGE_BACKEND=drive,PUBLIC_URL=$PUBLIC_URL,GOOGLE_SERVICE_ACCOUNT_JSON=/secrets/drive/key.json"
ENV="$ENV,DRIVE_ROOT_FOLDER_ID=$DRIVE_ROOT_FOLDER_ID,DRIVE_INVOICES_FOLDER_ID=$DRIVE_INVOICES_FOLDER_ID"
ENV="$ENV,DRIVE_BACKUPS_FOLDER_ID=$DRIVE_BACKUPS_FOLDER_ID,DRIVE_SHIPMENTS_FOLDER_ID=$DRIVE_SHIPMENTS_FOLDER_ID"
SECRETS="DATABASE_URL=database-url:latest,JWT_SECRET_KEY=jwt-secret:latest,BACKUP_ENCRYPTION_KEY=backup-key:latest,JOB_TOKEN=job-token:latest,/secrets/drive/key.json=drive-sa-key:latest"

echo "== 2/3 back up + migrate"
gcloud run jobs deploy erp-migrate --image "$TAG" --region "$REGION" --service-account "$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com" \
  --set-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" \
  --command scripts/migrate.sh --memory 1Gi --task-timeout 1800 --max-retries 0 --quiet
gcloud run jobs execute erp-migrate --region "$REGION" --wait

echo "== 3/3 deploy"
gcloud run deploy "$SERVICE" --image "$TAG" --region "$REGION" --service-account "$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com" \
  --add-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" \
  --memory 1Gi --cpu 1 --timeout 3600 --concurrency 80 --min-instances 0 --max-instances 3 \
  --no-invoker-iam-check --quiet
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
# ICEGATE read every 6 h (created once; later deploys leave it as is)
if ! gcloud scheduler jobs describe erp-icegate --location "$REGION" >/dev/null 2>&1; then
  TOKEN=$(gcloud secrets versions access latest --secret=job-token)
  gcloud scheduler jobs create http erp-icegate --location "$REGION" --schedule "20 */6 * * *" --time-zone "Asia/Kolkata" \
    --uri "$URL/internal/jobs/icegate" --http-method POST --headers "X-Job-Token=$TOKEN" --attempt-deadline 1800s --quiet
fi
# Google Sheets copy of the tracker every 15 min (Sheets API on, job created once)
gcloud services enable sheets.googleapis.com picker.googleapis.com drive.googleapis.com --quiet
if ! gcloud scheduler jobs describe erp-sheets-mirror --location "$REGION" >/dev/null 2>&1; then
  TOKEN=$(gcloud secrets versions access latest --secret=job-token)
  gcloud scheduler jobs create http erp-sheets-mirror --location "$REGION" --schedule "*/15 * * * *" --time-zone "Asia/Kolkata" \
    --uri "$URL/internal/jobs/sheets-mirror" --http-method POST --headers "X-Job-Token=$TOKEN" --attempt-deadline 300s --quiet
fi
echo "Released: $URL"
