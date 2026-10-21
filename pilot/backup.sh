#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p /var/backups/service-academy
ACADEMY_BACKUP="/var/backups/service-academy/academy-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec service-academy-db pg_dump -U academy -d academy -Fc > "$ACADEMY_BACKUP.partial"
test -s "$ACADEMY_BACKUP.partial"
mv "$ACADEMY_BACKUP.partial" "$ACADEMY_BACKUP"
# Check archive readability. Off-server copy must be configured separately.
docker exec -i service-academy-db pg_restore -l < "$ACADEMY_BACKUP" >/dev/null
