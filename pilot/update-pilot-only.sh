#!/usr/bin/env bash
# Upgrade Academy API only. Keeps PostgreSQL volume, Caddy, other apps and Telegram worker.
set -euo pipefail
cd /opt/service
CFG=/etc/service-academy.env
[[ -f "$CFG" ]] || { echo "Academy environment missing"; exit 1; }
for name in service-academy-db service-academy-api service-academy-web; do
  docker inspect "$name" >/dev/null || { echo "Missing container: $name"; exit 1; }
done
docker network inspect service-academy-net >/dev/null
docker exec service-academy-db pg_isready -U academy -d academy
# A failed backup must stop the release before changing any running container.
bash pilot/backup.sh
OLD_IMAGE="$(docker inspect --format '{{.Image}}' service-academy-api)"
RELEASE="service-academy-pilot:update-$(date -u +%Y%m%dT%H%M%SZ)"
docker build -t "$RELEASE" -f pilot/Dockerfile .
# Release gate must cover the same trainee/manager paths as CI, including
# service publication, onboarding and staged menu exams. All DB test suites
# use disposable schemas; production courses and attempts are not altered.
docker run --rm --network service-academy-net --env-file "$CFG" "$RELEASE" python -m unittest test_dishes test_cases test_pilot test_wine_cards test_menu_cards test_course_generation test_service_package test_menu_assessments test_onboarding
# Additive Academy-only schema change. Apply after backup, before switching the API.
# No rows or historical scores are deleted.
# All statements in schema.sql are additive (CREATE IF NOT EXISTS / ALTER ADD IF NOT EXISTS).
# Apply them to Academy DB only, after backup and isolated integration tests.
docker exec -i service-academy-db psql -U academy -d academy -v ON_ERROR_STOP=1 < pilot/schema.sql
echo "Backup, tests and Academy course migration OK. Replacing Academy API only."
docker rm -f service-academy-api
run_api() {
 docker run -d --name service-academy-api --restart unless-stopped \
   --network service-academy-net --memory 640m --env-file "$CFG" \
   --log-opt max-size=10m --log-opt max-file=3 "$1" >/dev/null
}
api_healthy() {
 for i in $(seq 1 30); do
   if docker exec service-academy-api python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2)" >/dev/null 2>&1; then
     return 0
   fi
   sleep 1
 done
 return 1
}
if ! run_api "$RELEASE" || ! api_healthy; then
  echo "New Academy API failed; rolling back previous image."
  docker rm -f service-academy-api >/dev/null 2>&1 || true
  run_api "$OLD_IMAGE"
  api_healthy || { echo "Rollback container unhealthy; check local logs."; exit 1; }
  echo "Rolled back to the previous API."; exit 1
fi
echo "Academy API updated. PostgreSQL, Caddy and Telegram bot worker were not recreated."
docker exec service-academy-api python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"
