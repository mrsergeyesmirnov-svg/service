#!/usr/bin/env bash
set -euo pipefail
STATE=/var/lib/service-academy-setup
for i in $(seq 1 720); do
 if [ -f "$STATE/done" ]; then
  install -m 600 "$STATE/config/service-academy.env" /etc/service-academy.env
  bash /opt/service/pilot/deploy-pilot.sh
  docker stop service-academy-setup >/dev/null
  exit 0
 fi
 sleep 5
done
# Expired page returns 410; credentials were never submitted.
docker stop service-academy-setup >/dev/null
