#!/usr/bin/env bash
# Opens a one-use HTTPS form; does not change or restart any running application.
set -euo pipefail
cd /opt/service
STATE=/var/lib/service-academy-ai-setup
install -d -m 700 "$STATE"
test ! -e "$STATE/access.json"
python3 - <<'PY'
from pathlib import Path
import hashlib,json,secrets,time,os
s=Path('/var/lib/service-academy-ai-setup');key=secrets.token_hex(32)
for name,value in [('access.json',json.dumps({'hash':hashlib.sha256(key.encode()).hexdigest(),'expires':time.time()+3600})),('link','https://service.139.100.239.232.sslip.io/ai-setup/#'+key)]:
    fd=os.open(s/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:f.write(value)
PY
IMAGE=$(docker inspect --format '{{.Image}}' service-academy-api)
docker run -d --name service-academy-ai-setup --network service-academy-net --memory 64m --user 0:0 --read-only --cap-drop ALL --security-opt no-new-privileges --log-driver none -v "$STATE:/setup-state" -v /opt/service/pilot/ai_setup_web.py:/app/ai_setup_web.py:ro --entrypoint python "$IMAGE" /app/ai_setup_web.py
python3 - <<'PY'
from pathlib import Path
p=Path('.deploy/Caddyfile');s=p.read_text()
if 'handle /ai-setup/*' not in s:
    if ' encode gzip' not in s:raise SystemExit('Expected Caddy anchor missing')
    p.with_name('Caddyfile.before-ai-setup').write_text(s)
    s=s.replace(' encode gzip',' handle /ai-setup/* {\n  request_body {\n   max_size 2KB\n  }\n  reverse_proxy service-academy-ai-setup:8765\n }\n encode gzip',1)
    p.write_text(s)
PY
if ! docker exec service-academy-web caddy validate --config /etc/caddy/Caddyfile; then
 cp .deploy/Caddyfile.before-ai-setup .deploy/Caddyfile
 docker stop service-academy-ai-setup >/dev/null
 exit 1
fi
docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile
systemd-run --unit=service-academy-ai-setup-expiry --on-active=1h /usr/bin/docker stop service-academy-ai-setup
cat "$STATE/link"
printf '\n'
