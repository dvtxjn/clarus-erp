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
# ICEGATE mailbox (read-only Gmail): the OAuth client's secret, once it's been saved as google-oauth-secret
ENV="$ENV,GOOGLE_OAUTH_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID,GMAIL_PUBSUB_TOPIC=projects/$PROJECT/topics/icegate-mail"
if gcloud secrets describe google-oauth-secret >/dev/null 2>&1; then
  SECRETS="$SECRETS,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-secret:latest"
fi

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
gcloud services enable sheets.googleapis.com picker.googleapis.com drive.googleapis.com gmail.googleapis.com pubsub.googleapis.com --quiet
# ICEGATE mailbox: Gmail tells Pub/Sub about new mail -> Pub/Sub pushes to the ERP at once (created once)
if ! gcloud pubsub topics describe icegate-mail >/dev/null 2>&1; then
  gcloud pubsub topics create icegate-mail --quiet
  gcloud pubsub topics add-iam-policy-binding icegate-mail \
    --member serviceAccount:gmail-api-push@system.gserviceaccount.com --role roles/pubsub.publisher --quiet >/dev/null
fi
if ! gcloud pubsub subscriptions describe icegate-mail-push >/dev/null 2>&1; then
  TOKEN=$(gcloud secrets versions access latest --secret=job-token)
  gcloud pubsub subscriptions create icegate-mail-push --topic icegate-mail --ack-deadline 120 \
    --push-endpoint "$PUBLIC_URL/internal/gmail/push?token=$TOKEN" --quiet
fi
if ! gcloud scheduler jobs describe erp-gmail --location "$REGION" >/dev/null 2>&1; then
  TOKEN=$(gcloud secrets versions access latest --secret=job-token)
  gcloud scheduler jobs create http erp-gmail --location "$REGION" --schedule "*/15 * * * *" --time-zone "Asia/Kolkata" \
    --uri "$URL/internal/jobs/gmail" --http-method POST --headers "X-Job-Token=$TOKEN" --attempt-deadline 600s --quiet
fi
if ! gcloud scheduler jobs describe erp-sheets-mirror --location "$REGION" >/dev/null 2>&1; then
  TOKEN=$(gcloud secrets versions access latest --secret=job-token)
  gcloud scheduler jobs create http erp-sheets-mirror --location "$REGION" --schedule "*/15 * * * *" --time-zone "Asia/Kolkata" \
    --uri "$URL/internal/jobs/sheets-mirror" --http-method POST --headers "X-Job-Token=$TOKEN" --attempt-deadline 300s --quiet
fi
# ICEGATE portal lookups (created once): BE status + queries every 30 min 08–22 IST, duty challans every morning.
# They do nothing until the ICEGATE login is entered on the Customs mail page.
for j in "erp-icegate-status|*/30 8-21 * * *|icegate-status" "erp-icegate-challans|0 9 * * *|icegate-challans"; do
  IFS='|' read -r NAME CRON JOB <<< "$j"
  if ! gcloud scheduler jobs describe "$NAME" --location "$REGION" >/dev/null 2>&1; then
    TOKEN=$(gcloud secrets versions access latest --secret=job-token)
    gcloud scheduler jobs create http "$NAME" --location "$REGION" --schedule "$CRON" --time-zone "Asia/Kolkata" \
      --uri "$URL/internal/jobs/$JOB" --http-method POST --headers "X-Job-Token=$TOKEN" --attempt-deadline 900s --quiet
  fi
done
echo "Released: $URL"
