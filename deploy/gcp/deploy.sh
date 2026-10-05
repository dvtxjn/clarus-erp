#!/usr/bin/env bash
# Release a new version: build -> back up + migrate (Cloud Run Job) -> deploy.  Run in Cloud Shell:
#   cd ~/clarus-erp && git pull && bash deploy/gcp/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null
TAG="$IMAGE:$(git rev-parse --short HEAD)"
API_KEY=$(gcloud secrets versions access latest --secret=vite-google-api-key | tr -d "[:space:]")  # a stray newline breaks the Picker
# The key ends up in the public website, so only a Google browser key (AIza…) may go in — never another secret
if [[ ! "$API_KEY" =~ ^AIza[0-9A-Za-z_-]{35}$ ]]; then
  echo "STOP: secret vite-google-api-key is not a Google API key (should start with AIza, 39 characters)." >&2
  echo "Fix:  read -rp 'Picker API key: ' K && printf '%s' \"\$K\" | gcloud secrets versions add vite-google-api-key --data-file=-" >&2
  exit 1
fi

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
  --memory 1Gi --cpu 1 --timeout 3600 --concurrency 80 --min-instances 1 --max-instances 3 \
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
gcloud pubsub topics describe icegate-mail >/dev/null 2>&1 || gcloud pubsub topics create icegate-mail --quiet
# Gmail's push account is outside the company domain: an org policy ("domain restricted sharing") may refuse it.
# Then mail is still read by the 15-minute check; see PROGRESS.md for the one-time policy exception.
PUSH_OK=1
if ! gcloud pubsub topics get-iam-policy icegate-mail --format=json 2>/dev/null | grep -q gmail-api-push; then
  gcloud pubsub topics add-iam-policy-binding icegate-mail \
    --member serviceAccount:gmail-api-push@system.gserviceaccount.com --role roles/pubsub.publisher --quiet >/dev/null 2>&1 \
    || { PUSH_OK=0; echo "!! Instant mail push not enabled (org policy blocks gmail-api-push) — the 15-minute check still reads mail."; }
fi
if [ "$PUSH_OK" = 1 ] && ! gcloud pubsub subscriptions describe icegate-mail-push >/dev/null 2>&1; then
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
# ICEGATE portal login is parked (it used up the OTP limit): remove its scheduler jobs if they exist
for NAME in erp-icegate-status erp-icegate-challans; do
  if gcloud scheduler jobs describe "$NAME" --location "$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs delete "$NAME" --location "$REGION" --quiet
  fi
done
# uptime alert (created once; e-mail when the site stops answering) — never stops a release
bash deploy/gcp/uptime.sh || echo "(uptime alert not set up — run: bash deploy/gcp/uptime.sh)"
echo "Released: $URL"
