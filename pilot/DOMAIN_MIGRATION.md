# Перенос MOJO Academy на отдельный поддомен PulsTeam

Цель: подключить **academy.pulseteam.online** к действующему российскому
серверу Академии, не мигрируя PostgreSQL, не ломая PulsTeam,
`premium-ai-manager` и другие сервисы Selectel.

> Проверить написание и право управления доменом в DNS-панели владельца.
> Домен указан как предполагаемый; его реальное состояние не проверено.
> Не отключать рабочий адрес `sslip.io` до успешной приёмки.

## 1. DNS (сделать у регистратора)

Создать **A** запись:

- `academy` → `139.100.239.232` (сверить с актуальным IP сервера);
- TTL 300 на время миграции;
- если у поддомена есть устаревшие AAAA, CNAME или ещё A-записи —
  привести конфигурацию в порядок до переключения.

Не менять записи корневого PulsTeam, `www` и `api`.
Не использовать CDN/проксирование до подтверждённой работы прямого HTTPS.

## 2. На сервере Selectel

Команды выполнять в консоли сервера. Не публиковать env и токены.

```bash
cd /opt/service
git status --short
git pull --ff-only origin main
sudo ACADEMY_DOMAIN=academy.pulseteam.online bash pilot/configure-domain.sh
```

Если `git status` содержит незнакомые изменения, сначала разобраться с ними.
Скрипт добавляет **только новый virtual host** в Caddyfile с бэкапом,
валидирует конфигурацию, делает reload **того же Caddy**; не создаёт
новых контейнеров, не меняет конфигурации иных приложений, БД и bot worker.
Для TLS Caddy должен иметь доступ к ACME, а входящие 80/443 должны работать.

Проверка с компьютера или телефона в российской сети:

```bash
curl -Iv --max-time 15 https://academy.pulseteam.online/pilot/
curl -fsS --max-time 15 https://academy.pulseteam.online/api/health
```

`database:true` = серверная БД отвечает.
`telegram_configured:true` = есть токен и ID владельца, **не** связь с Telegram.
`telegram_bot_connected:true` = бот успешно опрашивал Telegram API
за последние 120 секунд. Если false — читать логи worker и проверять
сеть **именно с сервера**.

## 3. Переключить ссылки после проверки HTTPS

Изменить **только** `PUBLIC_URL` в файле `/etc/service-academy.env`
(права 600) на `https://academy.pulseteam.online/pilot/`.
Не выводить и не пересылать содержимое env в чаты.

Затем **пересоздать только** контейнер `service-academy-bot` с обновлённым
`--env-file /etc/service-academy.env`. Простой `docker restart` НЕ
применяет новые переменные среды Docker. Пересоздание делать после проверки
исходящего соединения сервера с `api.telegram.org:443`.
Для будущих релизов `pilot/update-bot-only.sh` обновляет worker вместе с
образом API, но при одинаковом образе сейчас не пересоздаёт его.

В `@BotFather` открыть настройки `@skill_mojo_bot` и установить новый
HTTPS URL для Mini App и Menu Button. Проверить, что URL открывается
из реального Telegram на iPhone.

## 4. Найти исходный сбой Telegram, а не только сайта

На сервере Selectel:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker logs --tail 80 service-academy-bot
curl -4sS -o /dev/null -w 'Bot API HTTP=%{http_code}, connect=%{time_connect}s, tls=%{time_appconnect}s\\n' --connect-timeout 5 --max-time 15 https://api.telegram.org
curl -fsS --max-time 10 https://academy.pulseteam.online/api/health
```

Код HTTP 404 от корня `api.telegram.org` сам по себе не означает обрыв сети —
существенны TCP/TLS и время подключения. Если возникают тайм-ауты, зафиксировать
время, сеть, IPv4/IPv6 и отправить в поддержку Selectel. Настройка DNS нашего
поддомена не исправит сетевой маршрут **от сервера** до Telegram.

## 5. Приёмка

1. Старый адрес всё ещё работает.
2. Новый адрес открывается по HTTPS через мобильный интернет РФ и Wi-Fi.
3. `/api/health` показывает связь с БД и отдельную свежесть Telegram worker.
4. Кнопка в BotFather открывает приложение на новом домене.
5. Стажёр входит, сдаёт тест, закрывает Telegram и видит результат после
   повторного входа.
6. `/start` и уведомления реально доходят (иначе проверять Bot API).
7. После полного теста обновить ссылки приглашений и внутреннюю документацию.

Для обновления кода использовать только `pilot/update-pilot-only.sh` и
`pilot/update-bot-only.sh` по инструкции `pilot/PILOT_RELEASE.md`.
**Не запускать** старый `pilot/deploy-pilot.sh`: он перезаписывает Caddyfile.

Ограничение: этот PR добавляет конфигурацию и диагностические функции,
но не заменяет доступ администратора к DNS, Selectel или BotFather. Также
он не доказывает, что новый домен исправит исходящие тайм-ауты Telegram.
