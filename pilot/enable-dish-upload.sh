#!/usr/bin/env bash
# Run only after Academy API update. Enable PDF and photo uploads without touching other apps.
set -euo pipefail
CFG=/opt/service/.deploy/Caddyfile
[[ -f "$CFG" ]] || { echo "Caddyfile not found; no changes applied"; exit 1; }
cp -p "$CFG" "$CFG.before-dishes"
python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);data=p.read_text()
matcher=' @dishupload path /api/dishes/import /api/dishes/*/photo'
updated=matcher+' /api/learning/import-pdf'
if updated in data:
 print('PDF upload routes already enabled')
elif matcher in data:
 p.write_text(data.replace(matcher,updated))
else:
 marker=' @pilot path /pilot/* /api/*\n'
 if data.count(marker)!=1: sys.exit('Unexpected Caddy config; no changes made')
 route=''' @dishupload path /api/dishes/import /api/dishes/*/photo /api/learning/import-pdf
 handle @dishupload {
  request_body {
   max_size 20MB
  }
  reverse_proxy service-academy-api:8000
 }
'''
 p.write_text(data.replace(marker,route+marker))
PY
if ! docker exec service-academy-web caddy validate --config /etc/caddy/Caddyfile; then
 cp -p "$CFG.before-dishes" "$CFG"
 echo "Caddy validation failed; previous config restored"
 exit 1
fi
if ! docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile; then
 cp -p "$CFG.before-dishes" "$CFG"
 docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile || true
 echo "Caddy reload failed; previous config restored"
 exit 1
fi
echo "Academy-only PDF import enabled. Other API requests remain limited to 300KB."
