"""Pull site sponsors from ss14.рф and push current Boosty role holders back. Does not replace the Boosty role flow."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import discord
from discord.ext import tasks

from cogs import role_events
from config import BOOSTY_ROLE_ID, GUILD_IDS, SITE_DONATE_URL, SITE_SPONSORS_URL, SPONSOR_SYNC_TOKEN, TRACKED_ROLES
from services.sponsors_file import read_lines, remove_sponsor, upsert_sponsor
from utils.logger import log_user_action

logger = logging.getLogger(__name__)


def _int_id(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class SiteSponsorSync:
    """Periodic HTTPS pull of site-paid sponsors and push of Boosty members. Missing env keeps Boosty-only bots running."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    def start(self) -> None:
        if not SITE_SPONSORS_URL or not SPONSOR_SYNC_TOKEN:
            logger.info("Синхронизация спонсоров сайта выключена: нет SITE_SPONSORS_URL или SPONSOR_SYNC_TOKEN")
            return
        if not self.sync_from_site.is_running():
            self.sync_from_site.start()

    def stop(self) -> None:
        if self.sync_from_site.is_running():
            self.sync_from_site.cancel()

    @tasks.loop(minutes=5)
    async def sync_from_site(self) -> None:
        await self._run()

    @sync_from_site.before_loop
    async def before_sync(self) -> None:
        await self.bot.wait_until_ready()

    async def _run(self) -> None:
        payload = await self._fetch()
        if payload is not None:
            await self._apply_site(payload)
        await self._push_boosty()
        await self._push_sponsors_file()
        await self._push_members()

    async def _apply_site(self, payload: dict) -> None:
        active = payload.get("active") or []
        revoked = payload.get("revoked") or []
        if not isinstance(active, list) or not isinstance(revoked, list):
            logger.error("Сайт вернул неожиданный JSON спонсоров")
            return

        role_events.skip_role_events = True
        try:
            for guild in self.bot.guilds:
                if guild.id not in GUILD_IDS:
                    continue
                for entry in active:
                    if isinstance(entry, dict):
                        await self._grant(guild, entry)
                for entry in revoked:
                    if isinstance(entry, dict):
                        await self._revoke(guild, entry)
            await asyncio.sleep(2)
        finally:
            role_events.skip_role_events = False

    async def _fetch(self) -> dict | None:
        headers = {"Authorization": f"Bearer {SPONSOR_SYNC_TOKEN}", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(SITE_SPONSORS_URL, headers=headers) as response:
                    if response.status != 200:
                        logger.warning("Сайт спонсоров ответил %s", response.status)
                        return None
                    data = await response.json()
                    return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.error("Не удалось получить спонсоров сайта: %s", exc)
            return None

    async def _member(self, guild: discord.Guild, discord_id: int) -> discord.Member | None:
        member = guild.get_member(discord_id)
        if member:
            return member
        try:
            return await guild.fetch_member(discord_id)
        except discord.NotFound:
            return None
        except discord.HTTPException as exc:
            logger.warning("Не удалось найти участника %s: %s", discord_id, exc)
            return None

    async def _grant(self, guild: discord.Guild, entry: dict) -> None:
        discord_id = _int_id(entry.get("discord_id"))
        role_id = _int_id(entry.get("role_id"))
        if discord_id is None or role_id is None or role_id not in TRACKED_ROLES:
            return
        member = await self._member(guild, discord_id)
        role = guild.get_role(role_id)
        if not member or not role:
            return
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="ss14rf site subscription")
                log_user_action(f"Site role added: {role.id}", member)
            except discord.HTTPException as exc:
                logger.error("Не удалось выдать роль сайта %s: %s", role.id, exc)
                return
        ckey = entry.get("ckey")
        if isinstance(ckey, str) and ckey:
            color = entry.get("color") if isinstance(entry.get("color"), str) else None
            await upsert_sponsor(member.name, ckey, role.id, color)

    async def _revoke(self, guild: discord.Guild, entry: dict) -> None:
        discord_id = _int_id(entry.get("discord_id"))
        if discord_id is None:
            return
        member = await self._member(guild, discord_id)
        username = member.name if member else str(entry.get("discord_username") or "")
        if member:
            tracked = [role for role in member.roles if role.id in TRACKED_ROLES]
            if tracked:
                try:
                    await member.remove_roles(*tracked, reason="ss14rf site subscription expired")
                    log_user_action("Site roles revoked", member)
                except discord.HTTPException as exc:
                    logger.error("Не удалось снять роли сайта у %s: %s", member.name, exc)
            try:
                await member.send(
                    "Подписка на сайте сс14.рф закончилась, поэтому роль спонсора снята. "
                    f"Продлить можно здесь: {SITE_DONATE_URL}. "
                    "Если у вас ещё действует Boosty, роль может вернуться сама."
                )
            except discord.Forbidden:
                logger.warning("Не удалось отправить DM об отзыве сайта пользователю %s", member.name)
        if username:
            await remove_sponsor(username)

    async def _push_boosty(self) -> None:
        url = _boosty_url()
        if not url:
            return
        members = await self._boosty_members()
        headers = {"Authorization": f"Bearer {SPONSOR_SYNC_TOKEN}", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(url, headers=headers, json={"members": members}) as response:
                    if response.status != 200:
                        logger.warning("Сайт Boosty ответил %s", response.status)
                        return
            logger.info("На сайт отправлено %s подписчиков Boosty", len(members))
        except Exception as exc:
            logger.error("Не удалось отправить подписчиков Boosty: %s", exc)

    async def _push_sponsors_file(self) -> None:
        url = _sponsors_file_url()
        if not url:
            return
        entries = await self._sponsor_file_entries()
        headers = {"Authorization": f"Bearer {SPONSOR_SYNC_TOKEN}", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(url, headers=headers, json={"entries": entries}) as response:
                    if response.status != 200:
                        logger.warning("Сайт файла спонсоров ответил %s", response.status)
                        return
            logger.info("На сайт отправлено %s строк файла спонсоров", len(entries))
        except Exception as exc:
            logger.error("Не удалось отправить файл спонсоров: %s", exc)

    async def _push_members(self) -> None:
        url = _members_url()
        if not url:
            return
        discord_ids = await self._all_member_ids()
        if not discord_ids:
            logger.warning("Список участников гильдии пуст, пропускаю синхронизацию плашки StarHorizon")
            return
        headers = {"Authorization": f"Bearer {SPONSOR_SYNC_TOKEN}", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(url, headers=headers, json={"discord_ids": discord_ids}) as response:
                    if response.status != 200:
                        logger.warning("Сайт участников гильдии ответил %s", response.status)
                        return
            logger.info("На сайт отправлено %s участников гильдии", len(discord_ids))
        except Exception as exc:
            logger.error("Не удалось отправить участников гильдии: %s", exc)

    async def _all_member_ids(self) -> list[str]:
        seen: set[str] = set()
        for guild in self.bot.guilds:
            if guild.id not in GUILD_IDS:
                continue
            if not guild.chunked:
                try:
                    await guild.chunk()
                except Exception as exc:
                    logger.warning("Не удалось загрузить участников %s: %s", guild.name, exc)
            for member in guild.members:
                if member.bot:
                    continue
                seen.add(str(member.id))
        return list(seen)

    async def _sponsor_file_entries(self) -> list[dict]:
        lines = await read_lines()
        entries: list[dict] = []
        seen: set[str] = set()
        for line in lines:
            parts = [part.strip() for part in line.strip().split(",")]
            if not parts or not parts[0]:
                continue
            username = parts[0]
            if username in seen:
                continue
            seen.add(username)
            ckey = parts[1] if len(parts) > 1 else ""
            role_id = parts[2] if len(parts) > 2 else None
            color = parts[4] if len(parts) > 4 else None
            entries.append({
                "username": username,
                "ckey": ckey or None,
                "role_id": role_id,
                "color": color,
            })
        return entries

    async def _boosty_members(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for guild in self.bot.guilds:
            if guild.id not in GUILD_IDS:
                continue
            if not guild.chunked:
                try:
                    await guild.chunk()
                except Exception as exc:
                    logger.warning("Не удалось загрузить участников %s: %s", guild.name, exc)
            role = guild.get_role(BOOSTY_ROLE_ID)
            if not role:
                continue
            for member in role.members:
                discord_id = str(member.id)
                if discord_id in seen:
                    continue
                tracked = [item for item in member.roles if item.id in TRACKED_ROLES]
                ordered_ids = [role_id for role_id in TRACKED_ROLES if any(item.id == role_id for item in tracked)]
                highest = next((item for item in tracked if ordered_ids and item.id == ordered_ids[-1]), None)
                seen[discord_id] = {
                    "discord_id": discord_id,
                    "discord_username": member.name,
                    "role_ids": [str(item.id) for item in tracked],
                    "role_name": highest.name if highest else None,
                }
        return list(seen.values())


def _boosty_url() -> str:
    url = (SITE_SPONSORS_URL or "").rstrip("/")
    if not url:
        return ""
    if url.endswith("/internal/sponsors"):
        return url[: -len("sponsors")] + "boosty"
    return url.rsplit("/", 1)[0] + "/boosty"


def _sponsors_file_url() -> str:
    url = (SITE_SPONSORS_URL or "").rstrip("/")
    if not url:
        return ""
    if url.endswith("/internal/sponsors"):
        return url[: -len("sponsors")] + "sponsors-file"
    return url.rsplit("/", 1)[0] + "/sponsors-file"


def _members_url() -> str:
    url = (SITE_SPONSORS_URL or "").rstrip("/")
    if not url:
        return ""
    if url.endswith("/internal/sponsors"):
        return url[: -len("sponsors")] + "discord-members"
    return url.rsplit("/", 1)[0] + "/discord-members"

