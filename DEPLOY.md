# Размещение на Selectel

Сервер из проекта premium-ai-manager: 139.100.239.232, Ubuntu 24.04.
Существующий сервис /opt/premium-ai-manager и /etc/premium-ai-manager.env не изменять.

Из среды разработки SSH недоступен (Network is unreachable). Следующие команды ещё НЕ выполнялись на сервере.

## 1. Открыть консоль Selectel или SSH

```bash
ssh root@139.100.239.232
```

Если /opt/service ещё нет:

```bash
git clone https://github.com/mrsergeyesmirnov-svg/service.git /opt/service
cd /opt/service
bash deploy.sh
```

Если каталог уже существует, проверить его remote перед обновлением, затем выполнить git pull --ff-only и bash deploy.sh.

По умолчанию HTTPS-хост: service.139.100.239.232.sslip.io. Это внешний DNS-сервис, код и данные остаются на Selectel. Для постоянного использования задайте собственный домен с A-записью на IP сервера:

```bash
ACADEMY_DOMAIN=academy.example.ru bash deploy.sh
```

Скрипт создаёт отдельный Caddy-контейнер service-academy-web. Не касается контейнеров ИИ-менеджера. Требуются свободные порты 80/443, доступ к Docker Hub, DNS и центру сертификации; входящие 80/443 должны быть разрешены в firewall Selectel и сервера. Caddy запрашивает сертификат автоматически; доступность сертификата нужно проверить.

```bash
docker logs --tail 50 service-academy-web
curl -I https://service.139.100.239.232.sslip.io
```

При занятом 80/443 скрипт останавливается. Не останавливайте существующий веб-сервер. Настройте отдельный HTTPS virtual host в текущем nginx/Caddy с корнем /opt/service/.deploy/public (предварительно скопируйте туда только index.html, app.js, style.css, invite.svg). Для nginx понадобится отдельная настройка TLS/сертификата. Секреты рядом со статическими файлами не размещать.

## 2. Подключить @skill_mojo_bot

В @BotFather: /mybots → skill_mojo_bot → Bot Settings → Configure Mini App → Enable Mini App → URL развёрнутого HTTPS-приложения. Названия пунктов могут зависеть от клиента. Дополнительно Menu Button можно настроить на тот же URL.

После настройки Main Mini App проверьте:
https://t.me/skill_mojo_bot?startapp=mojo_demo

QR в приложении ведёт на эту ссылку. До настройки Main Mini App ссылка не является подтверждённой рабочей точкой входа. Бот-токен для этой настройки и статического демо не нужен.

## Яндекс

В проекте ИИ-менеджера конфигурация находится в /etc/premium-ai-manager.env: YANDEX_API_KEY, YANDEX_MODEL_URI, YANDEX_SEARCH_FOLDER_ID. Секреты не считывались и не переносились. В будущем выделить Академии отдельную серверную конфигурацию и, предпочтительно, отдельный сервисный аккаунт с нужными правами. В браузер эти значения никогда не передавать.
