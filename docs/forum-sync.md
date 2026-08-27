# Зеркало форумов Discord ↔ сс14.рф

Двусторонний перенос четырёх Forum-каналов. Discord → сайт: события и `/import_forums`. Сайт → Discord: очередь `GET /internal/forum-outbox`. Обратно бот пишет от своего имени, в тексте ник (и ckey) автора с сайта.

Канонический документ сайта: `docs/forum.md` в репозитории сс14.рф. Править бота только через git, сначала локально, см. скилл `ss14-discord`.

## Каналы

| Discord channel id | Раздел на сайте |
|---|---|
| `1348648902160547850` | `/forum/predlozhka` Предложка |
| `1348260865773666356` | `/forum/bagi` Баги |
| `1349074375915077754` | `/forum/obsuzhdenie` Обсуждение |
| `1472354090569830463` | `/forum/otdel-kadrov` Отдел кадров |

Другие каналы бот игнорирует. Разделы сайта без `discord_channel_id` в Discord не уходят.

## Как работает

- Код: `cogs/forum_sync.py`. URL `PUT /internal/forum-import` и `GET /internal/forum-outbox` выводятся из `SITE_SPONSORS_URL` (как Boosty). Тот же Bearer `SPONSOR_SYNC_TOKEN`.
- Пустые URL или токен — зеркало выключено, остальные команды бота живут.
- История: slash `/import_forums`. Доступ: администратор гильдии или ник из `CAN_GIVES_ROLES`. Бот обходит активные и архивные треды, шлёт по одной теме, ретраит 429/5xx. Сообщения самого бота (посты с сайта) в импорт не входят.
- Discord → сайт: новые треды, сообщения, правки, удаления, архив/лок. Сайт идемпотентен по `discord_thread_id` / `discord_message_id`. Картинки сайт качает сам с Discord CDN. Гифки Tenor/Giphy в тексте сообщения сайт показывает как плеер; если в Discord только embed без ссылки, бот кладёт URL картинки в `attachments`. Уведомления на сайте не шлются.
- Сайт → Discord: бот каждые 2 секунды забирает очередь, создаёт тред или пишет в существующий, затем `POST /internal/forum-outbox/{id}/ack`. Свои сообщения и треды, где owner — этот бот, обратно на сайт не пушит — иначе цикл.
- Чтобы не задвоить тему, сначала сайт (API import + outbox), потом бот.

## Intents

Нужен privileged **Message Content** в Discord Developer Portal. Без него бот не видит тексты форумов. В коде: `intents.message_content = True`. Также Read Message History и Send Messages на форум-каналах.

Порядок выкладки: сначала сайт (разделы, `PUT /internal/forum-import`, `GET /internal/forum-outbox`), потом git pull бота, потом `/import_forums`. Прод бота не трогать без явной просьбы владельца.

## Проверка

Локально бот не направлять на production-сайт без запроса. Не запускать полный `main.py` с `SITE_SPONSORS_URL` на localhost: `SiteSponsorSync` тогда тянет локальных спонсоров и может снять Boosty-роли на живой гильдии. Разовый импорт истории: остановить контейнер бота, `python scripts/import_forums_once.py`, снова поднять бота. После выкладки: лог `Зеркало форума включено`, тема с Discord появляется на `/forum/predlozhka`, ответ на сайте — в том же треде Discord.
