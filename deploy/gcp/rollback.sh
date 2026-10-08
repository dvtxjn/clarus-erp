#!/usr/bin/env bash
# Instant rollback: send all traffic back to the previous working version (no rebuild — seconds).
#   bash deploy/gcp/rollback.sh              -> the version before the live one
#   bash deploy/gcp/rollback.sh <revision>   -> a specific one (list: gcloud run revisions list --service clarus-erp)
# The database is NOT rolled back (migrations only add; the deploy's backup is in Drive if ever needed).
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null
LIVE=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.traffic[0].revisionName)')
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  # newest ready revision older than the live one
  TARGET=$(gcloud run revisions list --service "$SERVICE" --region "$REGION" --sort-by='~metadata.creationTimestamp' \
    --filter="status.conditions.type=Ready AND status.conditions.status=True" --format='value(metadata.name)' \
    | awk -v live="$LIVE" 'found {print; exit} $0 == live {found=1}')
fi
[ -n "$TARGET" ] || { echo "No earlier version found." >&2; exit 1; }
echo "Live: $LIVE  ->  rolling back to: $TARGET"
gcloud run services update-traffic "$SERVICE" --region "$REGION" --to-revisions "$TARGET=100" --quiet
echo "Done. To undo the rollback: bash deploy/gcp/rollback.sh $LIVE"
