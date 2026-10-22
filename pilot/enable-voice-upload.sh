#!/usr/bin/env bash
# Only Academy voice uploads; preserve other Selectel services and Caddy routes.
set -euo pipefail
cd /opt/service
CFG=.deploy/Caddyfile
[[ -f "$CFG" ]] || { echo "Academy Caddy config missing; no changes made"; exit 1; }
cp -p "$CFG" "$CFG.before-voice"
python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);data=p.read_text()
if '@voiceupload path ' in data:
 print('Voice route already exists')
 sys.exit(0)
anchor=' @pilot path /pilot/* /api/*\n'
if data.count(anchor)!=1:
 sys.exit('Unexpected Caddy config; no changes made')
voice=''' @voiceupload path /api/voice/transcribe
 handle @voiceupload {
  request_body {
   max_size 3MB
  }
  reverse_proxy service-academy-api:8000
 }
'''
p.write_text(data.replace(anchor,voice+anchor))
PY
if ! docker exec service-academy-web caddy validate --config /etc/caddy/Caddyfile; then
 cp -p "$CFG.before-voice" "$CFG"
 echo "Caddy voice validation failed; previous file restored" >&2
 exit 1
fi
if ! docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile; then
 cp -p "$CFG.before-voice" "$CFG"
 docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile || true
 echo "Caddy voice reload failed; previous file restored" >&2
 exit 1
fi
echo "Academy voice upload route enabled; other apps untouched."
