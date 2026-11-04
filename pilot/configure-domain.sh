#!/usr/bin/env bash
# Add an Academy-only HTTPS virtual host to the EXISTING Caddy container.
# Does not move the database, restart Telegram, or modify other projects.
set -euo pipefail

cd /opt/service
DOMAIN="${ACADEMY_DOMAIN:-}"
SERVER_IP="${ACADEMY_SERVER_IPV4:-139.100.239.232}"
CONF=/opt/service/.deploy/Caddyfile
WEB=service-academy-web

if [[ ! "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$ ]]; then
  echo "Provide ACADEMY_DOMAIN (e.g. academy.pulseteam.online), without https://"
  exit 1
fi
if [[ ! "$SERVER_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "Invalid ACADEMY_SERVER_IPV4"
  exit 1
fi
test -f "$CONF" || { echo "Caddyfile not found: $CONF"; exit 1; }
docker inspect "$WEB" >/dev/null || { echo "Academy Caddy container missing"; exit 1; }
docker inspect service-academy-api >/dev/null || { echo "Academy API container missing"; exit 1; }
docker inspect -f '{{json .NetworkSettings.Networks}}' "$WEB" | grep -q service-academy-net || {
  echo "Academy Caddy is not connected to service-academy-net"
  exit 1
}

# Prevent accidental certificate requests against the wrong address.
RESOLVED_IPS="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u || true)"
if ! printf '%s\n' "$RESOLVED_IPS" | grep -Fxq "$SERVER_IP"; then
  echo "DNS A record for $DOMAIN must point to $SERVER_IP before this step."
  echo "Currently resolved IPv4: ${RESOLVED_IPS:-none}"
  exit 2
fi
if [[ "$(printf '%s\n' "$RESOLVED_IPS" | grep -Ec '^[0-9]+\.' || true)" -ne 1 ]]; then
  echo "Multiple IPv4 targets detected; verify every target serves the Academy."
  exit 2
fi
if getent ahostsv6 "$DOMAIN" | grep -q 'STREAM'; then
  echo "Warning: AAAA record detected. Confirm IPv6 TLS/routing or remove the AAAA record."
fi

if grep -Fq "# BEGIN ACADEMY HOST $DOMAIN" "$CONF"; then
  echo "Academy Caddy host already present: $DOMAIN"
  exit 0
fi
if grep -Fq "$DOMAIN" "$CONF"; then
  echo "Domain appears elsewhere in existing Caddyfile; do not overwrite it."
  exit 3
fi

BACKUP="${CONF}.before-academy-domain-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$CONF" "$BACKUP"
# Keep the same bind-mounted inode (Caddyfile is mounted into Docker).
cat >> "$CONF" <<EOF

# BEGIN ACADEMY HOST $DOMAIN
$DOMAIN {
  encode gzip
  header X-Content-Type-Options nosniff
  redir /pilot /pilot/ 308
  handle /api/* {
    reverse_proxy service-academy-api:8000
  }
  handle /pilot/* {
    reverse_proxy service-academy-api:8000
  }
  handle {
    redir /pilot/ 302
  }
}
# END ACADEMY HOST $DOMAIN
EOF

if ! docker exec "$WEB" caddy validate --config /etc/caddy/Caddyfile; then
  cat "$BACKUP" > "$CONF"
  echo "Caddy validation failed; old config restored."
  exit 4
fi
if ! docker exec "$WEB" caddy reload --config /etc/caddy/Caddyfile; then
  cat "$BACKUP" > "$CONF"
  docker exec "$WEB" caddy reload --config /etc/caddy/Caddyfile || true
  echo "Caddy reload failed; old config restored."
  exit 5
fi
echo "Added HTTPS host: https://$DOMAIN/pilot/"
echo "Old domain stays active. Database, API, bot and other services were not restarted."
echo "Verify HTTPS and then update BotFather and PUBLIC_URL as described in pilot/DOMAIN_MIGRATION.md."
