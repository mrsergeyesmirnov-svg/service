#!/usr/bin/env bash
set -euo pipefail
cd /opt/service
STATE=/var/lib/service-academy-setup
install -d -m 700 "$STATE" "$STATE/config"
# Refuse to overwrite configured credentials or a previous active setup.
test ! -e "$STATE/access.json"
python3 - <<'PY'
from pathlib import Path
import hashlib,json,secrets,time
p=Path('/etc/service-academy.env');cfg=dict(x.split('=',1) for x in p.read_text().splitlines() if '=' in x)
if cfg.get('BOT_TOKEN'):raise SystemExit('Bot already configured')
s=Path('/var/lib/service-academy-setup');key=secrets.token_hex(16)
(s/'config/service-academy.env').write_text(p.read_text());(s/'config/service-academy.env').chmod(0o600)
(s/'access.json').write_text(json.dumps({'hash':hashlib.sha256(key.encode()).hexdigest(),'expires':time.time()+3600}));(s/'access.json').chmod(0o600)
(s/'link').write_text('https://service.139.100.239.232.sslip.io/setup/#'+key);(s/'link').chmod(0o600)
PY
docker run -d --name service-academy-setup --network service-academy-net --memory 64m --user 0:0 -v "$STATE:/setup-state" -v "$STATE/config:/config" -v /opt/service/pilot/setup_web.py:/app/setup_web.py:ro --entrypoint python service-academy-pilot /app/setup_web.py
python3 - <<'PY'
from pathlib import Path
p=Path('.deploy/Caddyfile');s=p.read_text();s=s.replace(' encode gzip',' handle /setup/* {\n  request_body {\n   max_size 2KB\n  }\n  reverse_proxy service-academy-setup:8765\n }\n encode gzip',1);p.write_text(s)
PY
docker exec service-academy-web caddy validate --config /etc/caddy/Caddyfile
docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile
systemd-run --unit=service-academy-setup-watch /bin/bash /opt/service/pilot/finish-setup.sh
cat "$STATE/link"
printf '\n'
