# Монитор статуса SS14

Сервис `services/server_status.py` каждые 5 минут запрашивает production status API StarHorizon и отражает результат в названии Discord-канала.

## Текущее поведение

- Endpoint по умолчанию: `http://ss14.starhorizon.ru:1212/status`.
- Discord channel ID по умолчанию: `1349094379465478164`.
- Онлайн: `🟢 Сервер онлайн • N игроков` с правильным склонением.
- Недоступный endpoint, таймаут, не-200 ответ или некорректный JSON: `🔴 Сервер офлайн`.
- Если имя уже актуально, Discord API не вызывается повторно.
- Первый запрос выполняется сразу после готовности Discord-бота, затем раз в 5 минут.

Настройки можно переопределить через `SS14_STATUS_URL` и `SS14_STATUS_CHANNEL_ID` в `.env`. Секреты в репозиторий не добавляются.

## Выкладка и проверка

Код хранится в GitHub-репозитории `LerkOFF/LerkBot_Horizon`. Production checkout на сервере `zurih` — `/opt/starhorizon_bot`, контейнер — `starhorizon-bot`.

```bash
ssh root@zurih
cd /opt/starhorizon_bot
git pull --ff-only origin master
docker compose up -d --build lerkbot
docker logs --since 5m starhorizon-bot
```

После запуска проверить deployed commit, лог контейнера и название канала. Боту требуется Discord-разрешение **Manage Channels**. В production checkout нельзя выполнять `git clean`, `git reset --hard` или удалять operational-файлы. Ручное изменение токена бота без отдельного запроса не выполнять.
