#!/usr/bin/env bash
# Fix "The API developer key is invalid" in the Google Drive picker. Run in Cloud Shell:
#   cd ~/clarus-erp && git pull && bash deploy/gcp/fix_picker_key.sh            (site + Picker/Drive APIs)
#   cd ~/clarus-erp && git pull && bash deploy/gcp/fix_picker_key.sh site-only  (site lock only)
# Finds the API key saved in secret vite-google-api-key (never prints it), then:
#   - turns on the Picker + Drive APIs in this project
#   - checks the key belongs to the same project as the Google sign-in (VITE_GOOGLE_APP_ID)
#   - allows it on the ERP's site (+ local dev) and for the Picker + Drive APIs only
# Then redeploy (deploy.sh) so the site is rebuilt with it.
set -euo pipefail
cd "$(dirname "$0")/../.."
source deploy/gcp/config.sh
gcloud config set project "$PROJECT" >/dev/null

echo "== APIs"
gcloud services enable picker.googleapis.com drive.googleapis.com apikeys.googleapis.com

NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
if [ "$NUMBER" != "$VITE_GOOGLE_APP_ID" ]; then
  echo "STOP: VITE_GOOGLE_APP_ID in config.sh is $VITE_GOOGLE_APP_ID but project $PROJECT is $NUMBER." >&2
  echo "The picker key, the sign-in client and the app id must all come from one project." >&2
  exit 1
fi

SAVED=$(gcloud secrets versions access latest --secret=vite-google-api-key | tr -d "[:space:]")
KEY_NAME=""
for name in $(gcloud services api-keys list --format='value(name)'); do
  if [ "$(gcloud services api-keys get-key-string "$name" --format='value(keyString)')" = "$SAVED" ]; then
    KEY_NAME="$name"; break
  fi
done
if [ -z "$KEY_NAME" ]; then
  echo "The saved key isn't one of this project's API keys — making a new one." >&2
  KEY_NAME=$(gcloud services api-keys create --display-name="ERP Drive picker" --format='value(response.name)' 2>/dev/null \
             || gcloud services api-keys list --filter='displayName="ERP Drive picker"' --format='value(name)' | head -1)
  gcloud services api-keys get-key-string "$KEY_NAME" --format='value(keyString)' | tr -d "[:space:]" \
    | gcloud secrets versions add vite-google-api-key --data-file=- >/dev/null
  echo "Saved the new key in secret vite-google-api-key."
fi

if [ "${1:-}" = "site-only" ]; then
  # Test: the picker still says "developer key is invalid" → drop the API list, keep the site lock.
  echo "== Restricting the key to the ERP site only (any API)"
  gcloud services api-keys update "$KEY_NAME" --clear-restrictions >/dev/null
  gcloud services api-keys update "$KEY_NAME" \
    --allowed-referrers="$PUBLIC_URL/*,http://localhost:5173/*" >/dev/null
else
  echo "== Restricting the key to the ERP site + Picker/Drive"
  gcloud services api-keys update "$KEY_NAME" \
    --allowed-referrers="$PUBLIC_URL/*,http://localhost:5173/*" \
    --api-target=service=picker.googleapis.com \
    --api-target=service=drive.googleapis.com >/dev/null
fi

echo "Done. Now redeploy:  bash deploy/gcp/deploy.sh"
echo "Also check: Google Cloud console > APIs & Services > Credentials > the OAuth client has $PUBLIC_URL under Authorised JavaScript origins."
