#!/usr/bin/env bash
# The SANDBOX (P4): a separate copy of the app for staff to try things on made-up data.
# Its own database (erp_sandbox, same Cloud SQL instance), its own login secret, local files,
# no Drive, no backups, no admin, no rates. Run in Cloud Shell:
#   cd ~/clarus-erp && git pull && bash deploy/gcp/sandbox.sh          # set up / update it
#   bash deploy/gcp/sandbox.sh --reset                                  # put the sample data back
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null
SB_SERVICE=clarus-erp-sandbox
SB_DB=erp_sandbox
TAG="$IMAGE:$(git rev-parse --short HEAD)"
SA="$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com"
exists() { "$@" >/dev/null 2>&1; }
secret() {  # name value
  exists gcloud secrets describe "$1" || gcloud secrets create "$1" --replication-policy automatic >/dev/null
  printf %s "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
  gcloud secrets add-iam-policy-binding "$1" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null
}

echo "== 1. image $TAG"
# the same image as the real app (built by deploy.sh); built here only if this version isn't yet
if ! exists gcloud artifacts docker images describe "$TAG"; then
  API_KEY=$(gcloud secrets versions access latest --secret=vite-google-api-key)
  gcloud builds submit --config deploy/gcp/cloudbuild.yaml --region "$REGION" \
    --substitutions "_IMAGE=$TAG,_VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID,_VITE_GOOGLE_API_KEY=$API_KEY,_VITE_GOOGLE_APP_ID=$VITE_GOOGLE_APP_ID" .
fi

echo "== 2. its own database + login secret (never the real ones)"
exists gcloud sql databases describe "$SB_DB" --instance "$DB_INSTANCE" || gcloud sql databases create "$SB_DB" --instance "$DB_INSTANCE"
if ! exists gcloud secrets describe database-url-sandbox; then
  REAL=$(gcloud secrets versions access latest --secret=database-url)
  secret database-url-sandbox "${REAL/\/$DB_NAME?/\/$SB_DB?}"
fi
exists gcloud secrets describe jwt-secret-sandbox || secret jwt-secret-sandbox "$(openssl rand -hex 32)"

ENV="APP_ENV=production,SANDBOX=1,AUTO_MIGRATE=0,JOBS_ENABLED=0,STORAGE_BACKEND=local"
SECRETS="DATABASE_URL=database-url-sandbox:latest,JWT_SECRET_KEY=jwt-secret-sandbox:latest"

echo "== 3. tables"
gcloud run jobs deploy erp-sandbox-migrate --image "$TAG" --region "$REGION" --service-account "$SA" \
  --set-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" \
  --command alembic --args upgrade,head --memory 512Mi --max-retries 0 --quiet
gcloud run jobs execute erp-sandbox-migrate --region "$REGION" --wait

echo "== 4. sample data (first time, or with --reset)"
gcloud run jobs deploy erp-sandbox-seed --image "$TAG" --region "$REGION" --service-account "$SA" \
  --set-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" \
  --command python --args scripts/seed_sandbox.py --memory 512Mi --max-retries 0 --quiet
if [ "${1:-}" = "--reset" ] || ! exists gcloud run services describe "$SB_SERVICE" --region "$REGION"; then
  gcloud run jobs execute erp-sandbox-seed --region "$REGION" --wait
fi

echo "== 5. the sandbox app"
gcloud run deploy "$SB_SERVICE" --image "$TAG" --region "$REGION" --service-account "$SA" \
  --add-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" \
  --memory 512Mi --cpu 1 --min-instances 0 --max-instances 1 --no-invoker-iam-check --quiet
echo "Sandbox: $(gcloud run services describe "$SB_SERVICE" --region "$REGION" --format='value(status.url)')"
echo "Demo login is shown on its login page."
