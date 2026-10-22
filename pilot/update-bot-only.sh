#!/usr/bin/env bash
# Update only Telegram Academy worker to the already-tested Academy API image.
set -euo pipefail
CFG=/etc/service-academy.env
for name in service-academy-api service-academy-bot; do
  docker inspect "$name" >/dev/null || { echo "Missing $name"; exit 1; }
done
[[ -f "$CFG" ]] || { echo "Missing Academy env file"; exit 1; }
OLD_IMAGE="$(docker inspect --format '{{.Image}}' service-academy-bot)"
NEW_IMAGE="$(docker inspect --format '{{.Image}}' service-academy-api)"
docker network inspect service-academy-net >/dev/null
run_bot(){
 docker run -d --name service-academy-bot --restart unless-stopped \
  --network service-academy-net --memory 128m --env-file "$CFG" \
  --log-opt max-size=10m --log-opt max-file=3 "$1" python worker.py >/dev/null
}
bot_ready(){
 for i in $(seq 1 12); do
   if docker logs service-academy-bot 2>&1 | grep -q '^Worker ready$'; then
      [[ "$(docker inspect --format '{{.State.Running}}' service-academy-bot)" == true ]] && return 0
   fi
   sleep 2
 done
 return 1
}
if [[ "$OLD_IMAGE" == "$NEW_IMAGE" ]]; then
 echo "Telegram bot already runs the current Academy image; no changes needed."
 exit 0
fi
docker rm -f service-academy-bot >/dev/null
if ! run_bot "$NEW_IMAGE" || ! bot_ready; then
 echo "New worker not ready; restoring previous image."
 docker rm -f service-academy-bot >/dev/null 2>&1 || true
 run_bot "$OLD_IMAGE"
 bot_ready || { echo "Rollback worker failed; inspect service-academy-bot logs privately."; exit 1; }
 echo "Restored previous Telegram worker image."
 exit 1
fi
echo "Telegram Academy worker updated; other containers untouched."
