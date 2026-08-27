"""Two-way Discord ↔ ss14.рф forum mirror. Empty SITE_SPONSORS_URL keeps the rest of the bot running."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import discord

from config import CAN_GIVES_ROLES, SITE_SPONSORS_URL, SPONSOR_SYNC_TOKEN

logger = logging.getLogger(__name__)

FORUM_CHANNEL_IDS = frozenset({
    1348648902160547850,  # предложка
    1348260865773666356,  # баги
    1349074375915077754,  # обсуждение
    1472354090569830463,  # отдел-кадров
})
MESSAGE_BATCH = 80
OUTBOX_POLL_SECONDS = 2


class ForumSync:
    """Mirrors four forum channels both ways: Discord events to PUT /internal/forum-import, site posts from GET /internal/forum-outbox."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self._listening = False
        self._importing = False
        self._outbox_task: asyncio.Task[None] | None = None

    def enabled(self) -> bool:
        return bool(SITE_SPONSORS_URL and SPONSOR_SYNC_TOKEN and _forum_import_url())

    def start(self) -> None:
        if not self.enabled():
            logger.info("Зеркало форума выключено: нет SITE_SPONSORS_URL или SPONSOR_SYNC_TOKEN")
            return
        if self._listening:
            return
        self._listening = True
        self.bot.add_listener(self.on_message, "on_message")
        self.bot.add_listener(self.on_message_edit, "on_message_edit")
        self.bot.add_listener(self.on_raw_message_delete, "on_raw_message_delete")
        self.bot.add_listener(self.on_thread_create, "on_thread_create")
        self.bot.add_listener(self.on_thread_update, "on_thread_update")
        self.bot.add_listener(self.on_thread_delete, "on_thread_delete")
        if self._outbox_task is None or self._outbox_task.done():
            self._outbox_task = asyncio.create_task(self._outbox_loop())
        logger.info("Зеркало форума включено")

    def stop(self) -> None:
        self._listening = False
        task = self._outbox_task
        self._outbox_task = None
        if task is not None:
            task.cancel()

    async def command_import(self, ctx: discord.ApplicationContext) -> None:
        if not self.enabled():
            await ctx.respond("Зеркало форума выключено: нет URL сайта или токена.", ephemeral=True)
            return
        if not _can_import(ctx.author):
            await ctx.respond("Недостаточно прав для импорта форумов.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        stats = await self.import_guild(ctx.guild)
        await ctx.followup.send(
            f"Импорт форумов: {stats['ok']} тем залито, ошибок {stats['errors']}.",
            ephemeral=True,
        )

    async def import_guild(self, guild: discord.Guild | None) -> dict[str, int]:
        stats = {"ok": 0, "errors": 0}
        if guild is None:
            return stats
        self._importing = True
        try:
            for channel_id in FORUM_CHANNEL_IDS:
                channel = guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(channel_id)
                    except discord.HTTPException as exc:
                        logger.warning("Не удалось открыть форум %s: %s", channel_id, exc)
                        stats["errors"] += 1
                        continue
                if not isinstance(channel, discord.ForumChannel):
                    logger.warning("Канал %s не форум", channel_id)
                    stats["errors"] += 1
                    continue
                threads = await _all_threads(channel)
                for thread in threads:
                    try:
                        if await self._push_thread(thread):
                            stats["ok"] += 1
                        else:
                            stats["errors"] += 1
                    except Exception as exc:
                        logger.error("Импорт треда %s: %s", thread.id, exc)
                        stats["errors"] += 1
                    await asyncio.sleep(0.4)
        finally:
            self._importing = False
        return stats

    async def on_message(self, message: discord.Message) -> None:
        if self._importing or message.guild is None or _is_own(self.bot, message.author):
            return
        thread = _forum_thread(message.channel)
        if thread is None:
            return
        await self._push_partial(thread, message)

    async def on_message_edit(self, _before: discord.Message, after: discord.Message) -> None:
        await self.on_message(after)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if self._importing:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except discord.HTTPException:
                return
        thread = _forum_thread(channel)
        if thread is None:
            return
        deleted: dict[str, Any] = {
            "discord_message_id": str(payload.message_id),
            "deleted": True,
        }
        body: dict[str, Any] = {
            "discord_channel_id": str(thread.parent_id),
            "discord_thread_id": str(thread.id),
        }
        if payload.message_id == thread.id:
            body["deleted"] = True
        else:
            body["messages"] = [deleted]
        await self._put(body)

    async def on_thread_create(self, thread: discord.Thread) -> None:
        if self._importing or thread.parent_id not in FORUM_CHANNEL_IDS:
            return
        if self.bot.user is not None and thread.owner_id == self.bot.user.id:
            return
        await self._push_thread(thread)

    async def on_thread_update(self, _before: discord.Thread, after: discord.Thread) -> None:
        if self._importing or after.parent_id not in FORUM_CHANNEL_IDS:
            return
        await self._put(_thread_meta(after))

    async def on_thread_delete(self, thread: discord.Thread) -> None:
        if thread.parent_id not in FORUM_CHANNEL_IDS:
            return
        payload = _thread_meta(thread)
        payload["deleted"] = True
        await self._put(payload)

    async def _push_thread(self, thread: discord.Thread) -> bool:
        starter, replies = await _history(thread, self.bot)
        if starter is None:
            if self.bot.user is not None and thread.owner_id == self.bot.user.id:
                return True
            logger.warning("У треда %s нет стартового сообщения", thread.id)
            return False
        ok = True
        for offset in range(0, max(len(replies), 1), MESSAGE_BATCH):
            chunk = replies[offset:offset + MESSAGE_BATCH]
            payload = _thread_meta(thread)
            if offset == 0:
                payload["starter"] = starter
            payload["messages"] = chunk
            if not await self._put(payload):
                ok = False
            if not replies:
                break
        return ok

    async def _push_partial(self, thread: discord.Thread, message: discord.Message) -> None:
        payload = _thread_meta(thread)
        packed = _pack_message(message)
        if message.id == thread.id:
            payload["starter"] = packed
        else:
            payload["messages"] = [packed]
        await self._put(payload)

    async def _outbox_loop(self) -> None:
        while self._listening:
            try:
                await self._drain_outbox()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Очередь форума сайт→Discord: %s", exc)
            await asyncio.sleep(OUTBOX_POLL_SECONDS)

    async def _drain_outbox(self) -> None:
        url = _forum_outbox_url()
        if not url:
            return
        payload = await self._request("GET", url)
        if not isinstance(payload, dict):
            return
        items = payload.get("items")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not isinstance(item_id, int):
                continue
            try:
                ids = await self._post_to_discord(item)
                acked = await self._request(
                    "POST",
                    f"{url}/{item_id}/ack",
                    json={
                        "discord_thread_id": ids["discord_thread_id"],
                        "discord_message_id": ids["discord_message_id"],
                    },
                )
                if acked is None:
                    logger.warning("Сайт не принял ack очереди форума %s", item_id)
            except Exception as exc:
                logger.error("Не удалось отправить пост %s в Discord: %s", item_id, exc)
                await self._request(
                    "POST",
                    f"{url}/{item_id}/fail",
                    json={"error": str(exc)[:500]},
                )

    async def _post_to_discord(self, item: dict[str, Any]) -> dict[str, str]:
        body = str(item.get("body") or "")[:2000]
        action = item.get("action")
        if action == "thread":
            channel = await self._forum_channel(int(item["discord_channel_id"]))
            title = str(item.get("title") or "Тема")[:100]
            kwargs: dict[str, Any] = {"name": title, "content": body or "*без текста*"}
            tags = _matching_tags(channel, item.get("tag"))
            if tags:
                kwargs["applied_tags"] = tags
            created = await channel.create_thread(**kwargs)
            thread = getattr(created, "thread", created)
            message = getattr(created, "message", None)
            if message is None:
                try:
                    message = await thread.fetch_message(thread.id)
                except discord.HTTPException:
                    message = None
            return {
                "discord_thread_id": str(thread.id),
                "discord_message_id": str(message.id if message is not None else thread.id),
            }
        if action != "reply":
            raise ValueError(f"неизвестное действие очереди: {action}")
        thread = await self._fetch_thread(int(item["discord_thread_id"]))
        if thread.archived:
            await thread.edit(archived=False, locked=False)
        message = await thread.send(content=body or "*без текста*")
        return {
            "discord_thread_id": str(thread.id),
            "discord_message_id": str(message.id),
        }

    async def _forum_channel(self, channel_id: int) -> discord.ForumChannel:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.ForumChannel):
            raise RuntimeError(f"канал {channel_id} не форум")
        return channel

    async def _fetch_thread(self, thread_id: int) -> discord.Thread:
        channel = self.bot.get_channel(thread_id)
        if channel is None:
            channel = await self.bot.fetch_channel(thread_id)
        if not isinstance(channel, discord.Thread):
            raise RuntimeError(f"{thread_id} не тред")
        return channel

    async def _put(self, payload: dict[str, Any]) -> bool:
        result = await self._request("PUT", _forum_import_url(), json=payload)
        return result is not None

    async def _request(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not url:
            return None
        headers = {
            "Authorization": f"Bearer {SPONSOR_SYNC_TOKEN}",
            "Accept": "application/json",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        timeout = aiohttp.ClientTimeout(total=120)
        for attempt in range(5):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.request(method, url, headers=headers, json=json) as response:
                        if response.status in (200, 201):
                            try:
                                data = await response.json(content_type=None)
                            except Exception:
                                return {}
                            return data if isinstance(data, dict) else {}
                        if response.status in (429, 500, 502, 503):
                            retry_after = response.headers.get("Retry-After")
                            delay = float(retry_after) if retry_after else 1.5 * (attempt + 1)
                            await asyncio.sleep(min(delay, 30))
                            continue
                        text = await response.text()
                        logger.warning("Сайт %s %s ответил %s: %s", method, url, response.status, text[:300])
                        return None
            except Exception as exc:
                logger.error("Запрос к сайту %s %s: %s", method, url, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
        return None


async def import_forums(ctx: discord.ApplicationContext) -> None:
    if forum_sync is None:
        await ctx.respond("Зеркало форума ещё не запущено.", ephemeral=True)
        return
    await forum_sync.command_import(ctx)


forum_sync: ForumSync | None = None


def bind(bot: discord.Bot) -> ForumSync:
    global forum_sync
    forum_sync = ForumSync(bot)
    return forum_sync


def _forum_import_url() -> str:
    return _site_internal_url("forum-import")


def _forum_outbox_url() -> str:
    return _site_internal_url("forum-outbox")


def _site_internal_url(name: str) -> str:
    url = (SITE_SPONSORS_URL or "").rstrip("/")
    if not url:
        return ""
    if url.endswith("/internal/sponsors"):
        return url[: -len("sponsors")] + name
    return url.rsplit("/", 1)[0] + "/" + name


def _can_import(member: discord.Member | discord.User) -> bool:
    if isinstance(member, discord.Member) and member.guild_permissions.administrator:
        return True
    names = {member.name}
    global_name = getattr(member, "global_name", None)
    if isinstance(global_name, str) and global_name:
        names.add(global_name)
    return any(name in CAN_GIVES_ROLES for name in names)


def _is_own(bot: discord.Bot, user: discord.abc.User | None) -> bool:
    return bot.user is not None and user is not None and user.id == bot.user.id


def _matching_tags(channel: discord.ForumChannel, tag_name: Any) -> list[Any]:
    if not isinstance(tag_name, str) or not tag_name.strip():
        return []
    wanted = tag_name.strip().casefold()
    found = []
    for tag in getattr(channel, "available_tags", None) or []:
        name = getattr(tag, "name", None)
        if isinstance(name, str) and name.strip().casefold() == wanted:
            found.append(tag)
            break
    return found


def _forum_thread(channel: discord.abc.Messageable) -> discord.Thread | None:
    if isinstance(channel, discord.Thread) and channel.parent_id in FORUM_CHANNEL_IDS:
        return channel
    return None


def _thread_meta(thread: discord.Thread) -> dict[str, Any]:
    flags = getattr(thread, "flags", None)
    return {
        "discord_channel_id": str(thread.parent_id),
        "discord_thread_id": str(thread.id),
        "title": thread.name,
        "tag": _tag(thread),
        "archived": bool(thread.archived),
        "locked": bool(thread.locked),
        "pinned": bool(getattr(flags, "pinned", False)),
    }


def _tag(thread: discord.Thread) -> str | None:
    tags = getattr(thread, "applied_tags", None) or []
    if not tags:
        return None
    name = getattr(tags[0], "name", None)
    return name if isinstance(name, str) and name else None


def _pack_message(message: discord.Message) -> dict[str, Any]:
    author = message.author
    content = message.content or ""
    attachments = [
        {
            "url": attachment.url,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
        }
        for attachment in message.attachments
    ]
    if not _body_has_gif_page(content):
        seen = {item["url"] for item in attachments}
        for embed in message.embeds:
            url = _embed_media_url(embed)
            if url is None or url in seen:
                continue
            seen.add(url)
            attachments.append(_embed_attachment(url))
    return {
        "discord_message_id": str(message.id),
        "discord_id": str(author.id),
        "discord_username": author.name,
        "display_name": getattr(author, "display_name", None) or author.name,
        "body": content,
        "created_at": message.created_at.isoformat(),
        "mentions": _mentions(message),
        "attachments": attachments,
    }


def _body_has_gif_page(content: str) -> bool:
    lower = content.lower()
    return "tenor.com/view/" in lower or "tenor.com/embed/" in lower or "giphy.com/gifs/" in lower


def _embed_media_url(embed: discord.Embed) -> str | None:
    for attr in ("image", "thumbnail", "video"):
        part = getattr(embed, attr, None)
        url = getattr(part, "url", None) if part is not None else None
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def _embed_attachment(url: str) -> dict[str, str]:
    path = url.split("?", 1)[0].lower()
    if path.endswith(".mp4"):
        return {"url": url, "filename": "gif.mp4", "content_type": "video/mp4"}
    if path.endswith(".webm"):
        return {"url": url, "filename": "gif.webm", "content_type": "video/webm"}
    if path.endswith(".webp"):
        return {"url": url, "filename": "gif.webp", "content_type": "image/webp"}
    return {"url": url, "filename": "gif.gif", "content_type": "image/gif"}


def _mentions(message: discord.Message) -> dict[str, str]:
    names: dict[str, str] = {}
    for user in message.mentions:
        names[str(user.id)] = user.display_name or user.name
    for channel in message.channel_mentions:
        name = getattr(channel, "name", None)
        if name:
            names[str(channel.id)] = name
    return names


async def _history(
    thread: discord.Thread,
    bot: discord.Bot,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    starter: dict[str, Any] | None = None
    replies: list[dict[str, Any]] = []
    try:
        async for message in thread.history(limit=None, oldest_first=True):
            if _is_own(bot, message.author):
                continue
            if message.type not in (
                discord.MessageType.default,
                discord.MessageType.reply,
                discord.MessageType.thread_starter_message,
            ) and message.content == "" and not message.attachments:
                continue
            packed = _pack_message(message)
            if starter is None:
                starter = packed
            elif packed["discord_message_id"] != starter["discord_message_id"]:
                replies.append(packed)
    except discord.Forbidden:
        logger.warning("Нет доступа к истории треда %s", thread.id)
    except discord.HTTPException as exc:
        logger.warning("История треда %s: %s", thread.id, exc)
    return starter, replies


async def _all_threads(channel: discord.ForumChannel) -> list[discord.Thread]:
    found: dict[int, discord.Thread] = {thread.id: thread for thread in channel.threads}
    async for thread in channel.archived_threads(limit=None):
        found[thread.id] = thread
    try:
        async for thread in channel.archived_threads(limit=None, private=True):
            found[thread.id] = thread
    except (discord.Forbidden, TypeError, discord.HTTPException):
        pass
    return list(found.values())
