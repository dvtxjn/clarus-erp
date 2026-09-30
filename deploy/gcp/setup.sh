#!/usr/bin/env bash
# ONE-TIME setup of Clarus ERP on Google Cloud. Run in Cloud Shell (console.cloud.google.com → >_):
#   gh auth login            (GitHub.com → HTTPS → log in with a web browser; the repo is private)
#   gh repo clone dvtxjn/clarus-erp ~/clarus-erp && cd ~/clarus-erp
#   (upload the service-account key with Cloud Shell's ⋮ → Upload; it lands in ~)
#   bash deploy/gcp/setup.sh ~/<key-file>.json
# It asks for: the backup encryption key, the Google Picker API key, and the first admin's password.
# Safe to re-run: anything that already exists is kept.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
KEY_FILE="${1:?usage: bash deploy/gcp/setup.sh <path to the service-account key .json>}"
[ -f "$KEY_FILE" ] || { echo "No such file: $KEY_FILE"; exit 1; }
gcloud config set project "$PROJECT" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
exists() { "$@" >/dev/null 2>&1; }
grant() {  # grant <member> <role>, retrying: a just-created identity takes a moment to exist everywhere
  for try in 1 2 3 4 5 6; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "$1" --role "$2" --condition None -q >/dev/null 2>&1 && return 0
    echo "   waiting for Google to register $1 ($try/5)"; sleep 20
  done
  gcloud projects add-iam-policy-binding "$PROJECT" --member "$1" --role "$2" --condition None -q >/dev/null
}

echo "== 1. services (one at a time — Google limits how many can be switched on per minute)"
ENABLED=$(gcloud services list --enabled --format='value(config.name)')
for svc in run sqladmin secretmanager cloudscheduler artifactregistry cloudbuild iam; do
  grep -qx "$svc.googleapis.com" <<<"$ENABLED" && { echo "   $svc: already on"; continue; }
  for try in 1 2 3 4 5 6; do
    gcloud services enable "$svc.googleapis.com" && { echo "   $svc: on"; break; }
    [ "$try" = 6 ] && { echo "Couldn't switch on $svc — wait a few minutes and run setup again."; exit 1; }
    echo "   Google says wait — retrying in 60 s ($try/5)"; sleep 60
  done
done

echo "== 2. image registry + build permissions"
exists gcloud artifacts repositories describe "$REPO" --location "$REGION" || \
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION"
BUILD_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  grant "serviceAccount:$BUILD_SA" "$role"
done

echo "== 3. the app's identity"
exists gcloud iam service-accounts describe "$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com" || \
  gcloud iam service-accounts create "$RUNTIME_SA" --display-name "Clarus ERP app"
for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
  grant "serviceAccount:$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com" "$role"
done

echo "== 4. database (Cloud SQL — the first time takes ~10 minutes)"
exists gcloud sql instances describe "$DB_INSTANCE" || \
  gcloud sql instances create "$DB_INSTANCE" --database-version "$DB_VERSION" --edition ENTERPRISE --tier "$DB_TIER" \
    --region "$REGION" --storage-type SSD --storage-size 10 --storage-auto-increase \
    --backup-start-time 20:30 --enable-point-in-time-recovery --retained-backups-count 14
exists gcloud sql databases describe "$DB_NAME" --instance "$DB_INSTANCE" || gcloud sql databases create "$DB_NAME" --instance "$DB_INSTANCE"

secret() {  # secret <name> <value>: create once (existing secrets are kept)
  exists gcloud secrets describe "$1" && return 0
  printf '%s' "$2" | gcloud secrets create "$1" --data-file=- --replication-policy automatic >/dev/null && echo "   secret $1 saved"
}
if ! exists gcloud secrets describe database-url; then
  DB_PASS=$(openssl rand -hex 24)
  gcloud sql users create "$DB_USER" --instance "$DB_INSTANCE" --password "$DB_PASS" 2>/dev/null || \
    gcloud sql users set-password "$DB_USER" --instance "$DB_INSTANCE" --password "$DB_PASS"
  secret database-url "postgresql://$DB_USER:$DB_PASS@/$DB_NAME?host=/cloudsql/$CONN"
fi

echo "== 5. secrets (typed here, stored in Secret Manager — never in git)"
secret jwt-secret "$(openssl rand -hex 32)"
secret job-token "$(openssl rand -hex 24)"
exists gcloud secrets describe drive-sa-key || gcloud secrets create drive-sa-key --data-file="$KEY_FILE" --replication-policy automatic >/dev/null
if ! exists gcloud secrets describe backup-key; then read -rsp "Backup encryption key (from the password manager): " V; echo; secret backup-key "$V"; fi
if ! exists gcloud secrets describe vite-google-api-key; then read -rp "Google Picker API key (AIza…): " V; secret vite-google-api-key "$V"; fi
ENV="APP_ENV=production,AUTO_MIGRATE=0,JOBS_ENABLED=0,STORAGE_BACKEND=drive,PUBLIC_URL=$PUBLIC_URL,GOOGLE_SERVICE_ACCOUNT_JSON=/secrets/drive/key.json"
ENV="$ENV,DRIVE_ROOT_FOLDER_ID=$DRIVE_ROOT_FOLDER_ID,DRIVE_INVOICES_FOLDER_ID=$DRIVE_INVOICES_FOLDER_ID"
ENV="$ENV,DRIVE_BACKUPS_FOLDER_ID=$DRIVE_BACKUPS_FOLDER_ID,DRIVE_SHIPMENTS_FOLDER_ID=$DRIVE_SHIPMENTS_FOLDER_ID"
SECRETS="DATABASE_URL=database-url:latest,JWT_SECRET_KEY=jwt-secret:latest,BACKUP_ENCRYPTION_KEY=backup-key:latest,JOB_TOKEN=job-token:latest,/secrets/drive/key.json=drive-sa-key:latest"
SA="$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com"

echo "== 6. build the app"
TAG="$IMAGE:$(git rev-parse --short HEAD)"
gcloud builds submit --config deploy/gcp/cloudbuild.yaml --region "$REGION" \
  --substitutions "_IMAGE=$TAG,_VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID,_VITE_GOOGLE_API_KEY=$(gcloud secrets versions access latest --secret=vite-google-api-key),_VITE_GOOGLE_APP_ID=$VITE_GOOGLE_APP_ID" .

echo "== 7. copy the data in: newest encrypted backup from Drive -> the new database (only if it's empty)"
gcloud run jobs deploy erp-import --image "$TAG" --region "$REGION" --service-account "$SA" \
  --set-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" --memory 1Gi --task-timeout 1800 --max-retries 0 \
  --command scripts/import_from_drive.sh --quiet
gcloud run jobs execute erp-import --region "$REGION" --wait

echo "== 8. first admin (divit@) + switch off the test logins"
if ! exists gcloud secrets describe first-admin-password; then
  read -rsp "Password for divit@claruslogistics.in (12+ characters): " V; echo; secret first-admin-password "$V"
fi
gcloud run jobs deploy erp-admin --image "$TAG" --region "$REGION" --service-account "$SA" \
  --set-cloudsql-instances "$CONN" --set-env-vars "$ENV,ADMIN_EMAIL=divit@claruslogistics.in,ADMIN_NAME=Divit,DISABLE_DEFAULT_USERS=1" \
  --set-secrets "$SECRETS,ADMIN_PASSWORD=first-admin-password:latest" --memory 512Mi --max-retries 0 \
  --command python --args scripts/create_admin.py --quiet
gcloud run jobs execute erp-admin --region "$REGION" --wait

echo "== 9. migrate + deploy the web app"
SKIP_BUILD=1 TAG_OVERRIDE="$TAG" bash deploy/gcp/deploy.sh
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')

echo "== 10. timers: backup check hourly (makes one every 12 h), Drive retry every 15 min"
TOKEN=$(gcloud secrets versions access latest --secret=job-token)
for j in "erp-backup|7 * * * *|backup" "erp-drive-retry|*/15 * * * *|drive-retry" "erp-icegate|20 */6 * * *|icegate"; do
  IFS='|' read -r NAME CRON JOB <<<"$j"
  exists gcloud scheduler jobs describe "$NAME" --location "$REGION" || \
    gcloud scheduler jobs create http "$NAME" --location "$REGION" --schedule "$CRON" --time-zone "Asia/Kolkata" \
      --uri "$URL/internal/jobs/$JOB" --http-method POST --headers "X-Job-Token=$TOKEN" --attempt-deadline 900s
done

echo "== 11. your address"
gcloud beta run domain-mappings create --service "$SERVICE" --domain "$DOMAIN" --region "$REGION" 2>&1 || true
gcloud beta run domain-mappings describe --domain "$DOMAIN" --region "$REGION" --format='table(status.resourceRecords[].type,status.resourceRecords[].rrdata)' 2>&1 || true
echo
echo "DONE. The app is at $URL (and at https://$DOMAIN once the DNS record above is added)."
echo "Log in as divit@claruslogistics.in. Then delete the temporary secret:  gcloud secrets delete first-admin-password"
