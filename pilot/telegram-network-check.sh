#!/usr/bin/env bash
# Read-only check. Run on the SAME Selectel machine as service-academy-bot.
# No bot token, env dumps, account IDs or contact data are printed.
set -uo pipefail
printf 'Checked UTC: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo '--- Telegram Bot API IPv4/TLS ---'
curl --ipv4 --silent --show-error --output /dev/null \
  --connect-timeout 5 --max-time 15 \
  --write-out 'http=%{http_code} tcp=%{time_connect}s tls=%{time_appconnect}s remote_ip=%{remote_ip}\n' \
  https://api.telegram.org/
case $? in
  0) echo 'Transport reached Telegram: HTTP 404 on / is acceptable.' ;;
  *) echo 'Transport FAILED (DNS, TCP, TLS or timeout); investigate Selectel egress.' ;;
esac
echo '--- Academy API via local Docker network ---'
if docker inspect service-academy-api >/dev/null 2>&1; then
  docker exec service-academy-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5).read().decode())" || true
else
  echo 'Academy API container missing'
fi
echo '--- Container state (Academy only) ---'
for name in service-academy-api service-academy-bot service-academy-db; do
  docker inspect -f '{{.Name}} running={{.State.Running}} restarts={{.RestartCount}}' "$name" 2>/dev/null || true
done
