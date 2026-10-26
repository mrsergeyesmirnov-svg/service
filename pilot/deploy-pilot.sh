#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CFG=/etc/service-academy.env
if [ ! -f "$CFG" ]; then
  umask 077
  python3 - <<'PY'
import secrets
p=secrets.token_hex(24)
with open('/etc/service-academy.env','x') as f:
 f.write('POSTGRES_PASSWORD='+p+'\nPOSTGRES_USER=academy\nPOSTGRES_DB=academy\nDATABASE_URL=postgresql://academy:'+p+'@service-academy-db/academy\nBOT_TOKEN=\nOWNER_TELEGRAM_ID=0\nPUBLIC_URL=https://service.139.100.239.232.sslip.io/pilot/\n')
PY
fi
chmod 600 "$CFG"
docker network inspect service-academy-net >/dev/null 2>&1 || docker network create service-academy-net
if ! docker inspect service-academy-db >/dev/null 2>&1; then
 docker run -d --name service-academy-db --restart unless-stopped --network service-academy-net --memory 320m --env-file "$CFG" -v service-academy-pg:/var/lib/postgresql/data --log-opt max-size=10m --log-opt max-file=3 postgres:16-alpine
fi
for i in $(seq 1 30); do docker exec service-academy-db pg_isready -U academy -d academy >/dev/null && break; sleep 1; done
docker exec service-academy-db pg_isready -U academy -d academy
docker build -t service-academy-pilot -f pilot/Dockerfile .
# Refuse deployment if core tests fail. Test database objects are isolated in a temporary schema.
docker run --rm --network service-academy-net --env-file "$CFG" service-academy-pilot python -m unittest test_cases test_pilot test_wine_cards
if docker inspect service-academy-api >/dev/null 2>&1; then docker rm -f service-academy-api; fi
docker run -d --name service-academy-api --restart unless-stopped --network service-academy-net --memory 256m --env-file "$CFG" --log-opt max-size=10m --log-opt max-file=3 service-academy-pilot
for i in $(seq 1 30); do docker exec service-academy-api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" >/dev/null 2>&1 && break; sleep 1; done
docker exec service-academy-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"
if ! docker inspect -f '{{json .NetworkSettings.Networks}}' service-academy-web | grep -q service-academy-net; then docker network connect service-academy-net service-academy-web; fi
cp .deploy/Caddyfile .deploy/Caddyfile.before-pilot
# Write in place: Caddyfile is an existing bind mount.
cat > .deploy/Caddyfile <<'EOF'
service.139.100.239.232.sslip.io {
 encode gzip
 header X-Content-Type-Options nosniff
 @pilot path /pilot/* /api/*
 handle @pilot {
  request_body {
   max_size 300KB
  }
  reverse_proxy service-academy-api:8000
 }
 redir /pilot /pilot/ 308
 handle {
  root * /srv
  file_server
 }
}
EOF
if ! docker exec service-academy-web caddy validate --config /etc/caddy/Caddyfile; then cat .deploy/Caddyfile.before-pilot > .deploy/Caddyfile; exit 1; fi
docker exec service-academy-web caddy reload --config /etc/caddy/Caddyfile
if docker inspect service-academy-bot >/dev/null 2>&1; then docker rm -f service-academy-bot; fi
if python3 - <<'PY'
d=dict(line.rstrip('\n').split('=',1) for line in open('/etc/service-academy.env') if '=' in line)
raise SystemExit(0 if d.get('BOT_TOKEN') and d.get('OWNER_TELEGRAM_ID','0')!='0' else 1)
PY
then
 docker run -d --name service-academy-bot --restart unless-stopped --network service-academy-net --memory 128m --env-file "$CFG" --log-opt max-size=10m --log-opt max-file=3 service-academy-pilot python worker.py
else
 echo 'База и API готовы. Для активации Telegram: sudo python3 /opt/service/pilot/configure.py'
fi
install -m 700 pilot/backup.sh /usr/local/sbin/service-academy-backup
printf '17 3 * * * root /usr/local/sbin/service-academy-backup\n' > /etc/cron.d/service-academy-backup
/usr/local/sbin/service-academy-backup
echo 'Пилот: https://service.139.100.239.232.sslip.io/pilot/'
