#!/usr/bin/env bash
# Run interactively on Selectel. Secrets never go through chat or GitHub.
set -euo pipefail
CFG=/etc/service-academy.env
if [[ ! -f "$CFG" ]]; then echo "Academy environment is missing" >&2; exit 1; fi
if [[ ! -t 0 ]]; then echo "Run this interactively in SSH, not in CI" >&2; exit 1; fi
read -r -p "Yandex AI Studio folder ID: " folder
read -r -p "Model [yandexgpt-5.1]: " model
model="${model:-yandexgpt-5.1}"
read -r -s -p "Service account API key (not echoed): " key
echo
if [[ ! "$folder" =~ ^[a-z0-9]{12,64}$ || ! "$model" =~ ^[a-zA-Z0-9._/-]+$ || ! "$key" =~ ^[[:graph:]]{20,500}$ ]]; then
 echo "Unexpected credentials format; file unchanged" >&2
 exit 1
fi
umask 077
tmp=$(mktemp /etc/service-academy.env.XXXXXX)
cleanup(){ rm -f "$tmp"; unset key; }
trap cleanup EXIT
grep -vE '^(YANDEX_API_KEY|YANDEX_FOLDER_ID|YANDEX_MODEL)=' "$CFG" > "$tmp" || true
printf 'YANDEX_API_KEY=%s\nYANDEX_FOLDER_ID=%s\nYANDEX_MODEL=%s\n' "$key" "$folder" "$model" >> "$tmp"
chmod 600 "$tmp"
chown --reference="$CFG" "$tmp"
mv -f "$tmp" "$CFG"
echo "AI variables saved securely. Now run pilot/update-pilot-only.sh to recreate the API container."
echo "After deployment: docker exec service-academy-api python check_ai.py"
