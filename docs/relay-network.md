# Сетевой маршрут к игровому серверу

Бот на `zurih` читает PostgreSQL SS14 и status API игрового сервера через SSH-туннель к `de-roma`. Прямые соединения между `zurih` и `starhorizon2` могут зависать после TCP handshake: ответные данные уходят с игрового хоста, но не достигают `zurih`.

## Текущая схема

- `scripts/ss14-relay-tunnel.sh` определяет шлюз Docker-сети `starhorizon_bot_default` и пробрасывает через `de-roma` локальные TCP-порты `15433` → `37.230.118.119:5433` и `11212` → `37.230.118.119:1212`.
- `deploy/ss14-relay-tunnel.service` держит туннель запущенным через systemd и восстанавливает его после обрыва. Если Docker-сеть ещё не создана при загрузке, сервис повторяет запуск.
- В production `.env` бота: `DB_HOST` — адрес шлюза Docker-сети, `DB_PORT=15433`, `SS14_STATUS_URL=http://<шлюз>:11212/status`.
- UFW на `zurih` пропускает к двум портам туннеля только контейнер бота из сети `starhorizon_bot_default`.
- Публичный ключ хоста бота на `de-roma` ограничен пересылкой к портам `22`, `1212` и `5433` игрового хоста. Порт `22` нужен для SSHFS sponsor-каталога. Ключ не разрешает запуск команд на `de-roma`.
- SSHFS `warp` монтируется с `ProxyJump=root@82.26.150.155`, затем bind-mount передаёт каталог в контейнер.

## Установка на `zurih`

После публикации изменений в Git и `git pull --ff-only origin master` в `/opt/starhorizon_bot`:

```bash
ln -s /opt/starhorizon_bot/deploy/ss14-relay-tunnel.service /etc/systemd/system/ss14-relay-tunnel.service
systemctl daemon-reload
systemctl enable --now ss14-relay-tunnel.service
```

При смене Docker-шлюза обновить адрес в `.env` и UFW-правила. Значения секретных переменных не выводить и не переносить в Git.

## Проверка

```bash
systemctl is-active ss14-relay-tunnel.service
ss -ltn | grep -E ':(15433|11212) '
docker exec starhorizon-bot python -c 'import urllib.request; print(urllib.request.urlopen("http://172.21.0.1:11212/status", timeout=8).status)'
docker logs --since 5m starhorizon-bot
findmnt -T /opt/starhorizon_bot/warp
```

Проверить запрос БД из контейнера через `asyncpg`, используя уже загруженные переменные `DB_*`, и ответ `/top_balance` в Discord. Для онлайна сверить название status-канала с числом игроков status API. Если SSHFS был переподключён, а контейнер видит старый mount, пересоздать контейнер через `docker compose up -d --build lerkbot`.
