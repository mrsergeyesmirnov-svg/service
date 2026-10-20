#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo 'Нужен Docker. На сервере ИИ-менеджера он уже установлен.'; exit 1; }
ACADEMY_DOMAIN="${ACADEMY_DOMAIN:-service.139.100.239.232.sslip.io}"
[[ "$ACADEMY_DOMAIN" =~ ^[a-zA-Z0-9.-]+$ ]] || { echo 'Некорректный домен'; exit 1; }
if ! docker inspect service-academy-web >/dev/null 2>&1; then
  if ss -ltn '( sport = :80 or sport = :443 )' | tail -n +2 | grep -q .; then
    echo 'Порты 80/443 заняты. Существующий веб-сервер не изменён.'
    echo "Подключите каталог $PWD к существующему HTTPS-хосту. См. DEPLOY.md."
    exit 2
  fi
fi
mkdir -p .deploy/public
cp index.html app.js style.css invite.svg .deploy/public/
printf '%s {\n root * /srv\n file_server\n encode gzip\n header X-Content-Type-Options nosniff\n}\n' "$ACADEMY_DOMAIN" > .deploy/Caddyfile
docker pull caddy:2-alpine
if docker inspect service-academy-web >/dev/null 2>&1; then docker rm -f service-academy-web; fi
docker run -d --name service-academy-web --restart unless-stopped -p 80:80 -p 443:443 \
  -v "$PWD/.deploy/public:/srv:ro" -v "$PWD/.deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v service-academy-caddy-data:/data -v service-academy-caddy-config:/config \
  --log-opt max-size=10m --log-opt max-file=3 caddy:2-alpine
printf '\nАдрес после выдачи сертификата: https://%s\n' "$ACADEMY_DOMAIN"
echo 'Проверка: docker logs --tail 50 service-academy-web'
echo 'В BotFather: /mybots → @skill_mojo_bot → Bot Settings → Configure Mini App → Enable Mini App.'
echo 'Укажите HTTPS-адрес выше. Пока TLS не выдан, Telegram Mini App не откроется.'
