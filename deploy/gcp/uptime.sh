#!/usr/bin/env bash
# Uptime alert (client, 2026-09-30): Google checks https://erp.claruslogistics.in/health every 5 minutes from
# several places; if it fails for ~5 minutes you get an e-mail (and another when it's back). Free tier.
# Safe to run again: the check, the e-mail channel and the alert are created once. Run in Cloud Shell:
#   bash deploy/gcp/uptime.sh                      (asks for the e-mail the first time)
#   ALERT_EMAIL=you@claruslogistics.in bash deploy/gcp/uptime.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null
gcloud services enable monitoring.googleapis.com --quiet

NAME="erp-uptime"
# 1. the check
CHECK=$(gcloud monitoring uptime list-configs --filter="displayName=$NAME" --format="value(name)" 2>/dev/null | head -1)
if [ -z "$CHECK" ]; then
  gcloud monitoring uptime create "$NAME" --resource-type=uptime-url \
    --resource-labels="host=$DOMAIN,project_id=$PROJECT" --protocol=https --path=/health \
    --period=5 --timeout=10 --quiet
  CHECK=$(gcloud monitoring uptime list-configs --filter="displayName=$NAME" --format="value(name)" | head -1)
fi
CHECK_ID="${CHECK##*/}"
echo "   uptime check: $CHECK_ID"

# 2. where the alert goes (e-mail)
CHANNEL=$(gcloud beta monitoring channels list --filter='displayName="ERP alerts"' --format="value(name)" 2>/dev/null | head -1)
if [ -z "$CHANNEL" ]; then
  EMAIL="${ALERT_EMAIL:-}"
  [ -z "$EMAIL" ] && read -rp "E-mail for 'ERP is down' alerts: " EMAIL
  CHANNEL=$(gcloud beta monitoring channels create --display-name="ERP alerts" --type=email \
    --channel-labels="email_address=$EMAIL" --format="value(name)")
fi

# 3. the alert: the check failing from more than one place for 5 minutes
if [ -z "$(gcloud alpha monitoring policies list --filter='displayName="ERP is down"' --format='value(name)' 2>/dev/null)" ]; then
  POLICY=$(mktemp)
  cat > "$POLICY" <<JSON
{
  "displayName": "ERP is down",
  "documentation": {"content": "https://$DOMAIN/health isn't answering. Check Cloud Run (service $SERVICE) and Cloud SQL ($DB_INSTANCE) in the console.", "mimeType": "text/markdown"},
  "combiner": "OR",
  "conditions": [{
    "displayName": "Uptime check failing",
    "conditionThreshold": {
      "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"$CHECK_ID\" AND resource.type=\"uptime_url\"",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                        "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.*"]}],
      "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "300s",
      "trigger": {"count": 1}
    }
  }],
  "notificationChannels": ["$CHANNEL"],
  "alertStrategy": {"autoClose": "1800s"}
}
JSON
  gcloud alpha monitoring policies create --policy-from-file="$POLICY" --quiet >/dev/null
  rm -f "$POLICY"
fi
echo "== uptime alert ready: e-mail when $DOMAIN stops answering (checked every 5 minutes)"
