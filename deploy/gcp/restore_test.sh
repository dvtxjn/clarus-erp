#!/usr/bin/env bash
# Backup restore test (client, 2026-09-30): proves the newest Drive backup can actually be restored.
# Makes a fresh scratch database erp_restore_check on the same Cloud SQL server, restores the backup into it,
# compares every table's row count with the backup's manifest, then removes the scratch database.
# The live database (erp_db) and Drive are never changed. Run in Cloud Shell after a deploy (~5 min):
#   bash deploy/gcp/restore_test.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null
SCRATCH=erp_restore_check
[ "$SCRATCH" != "$DB_NAME" ] || { echo "scratch database can't be the live one"; exit 1; }

# the image the live app runs now
TAG=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(spec.template.spec.containers[0].image)')
SECRETS="DATABASE_URL=database-url:latest,BACKUP_ENCRYPTION_KEY=backup-key:latest,/secrets/drive/key.json=drive-sa-key:latest"
ENV="STORAGE_BACKEND=drive,GOOGLE_SERVICE_ACCOUNT_JSON=/secrets/drive/key.json,DRIVE_ROOT_FOLDER_ID=$DRIVE_ROOT_FOLDER_ID,DRIVE_BACKUPS_FOLDER_ID=$DRIVE_BACKUPS_FOLDER_ID"

drop_scratch() {
  if gcloud sql databases describe "$SCRATCH" --instance "$DB_INSTANCE" >/dev/null 2>&1; then
    gcloud sql databases delete "$SCRATCH" --instance "$DB_INSTANCE" --quiet >/dev/null
  fi
}
echo "== 1/3 fresh scratch database $SCRATCH"
drop_scratch
gcloud sql databases create "$SCRATCH" --instance "$DB_INSTANCE" --quiet >/dev/null

echo "== 2/3 restore the newest backup into it"
gcloud run jobs deploy erp-restore-test --image "$TAG" --region "$REGION" --service-account "$RUNTIME_SA@$PROJECT.iam.gserviceaccount.com" \
  --set-cloudsql-instances "$CONN" --set-env-vars "$ENV" --set-secrets "$SECRETS" \
  --command python --args scripts/restore_check.py --memory 1Gi --task-timeout 1800 --max-retries 0 --quiet >/dev/null
OK=1
gcloud run jobs execute erp-restore-test --region "$REGION" --wait || OK=0
EXEC=$(gcloud run jobs executions list --job erp-restore-test --region "$REGION" --limit 1 --format='value(name)')
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=erp-restore-test AND labels.\"run.googleapis.com/execution_name\"=$EXEC" \
  --order asc --limit 300 --format='value(textPayload)' | sed '/^$/d'

echo "== 3/3 remove the scratch database"
drop_scratch
[ "$OK" = 1 ] && echo "== RESTORE TEST PASSED" || { echo "== RESTORE TEST FAILED — see above"; exit 1; }
