"""Pull active/revoked site sponsors from ss14.рф. Does not replace the Boosty role flow."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import discord
from discord.ext import tasks

from cogs import role_events
from config import GUILD_IDS, SITE_DONATE_URL, SITE_SPONSORS_URL, SPONSOR_SYNC_TOKEN, TRACKED_ROLES
from services.sponsors_file import remove_sponsor, upsert_sponsor
from utils.logger import log_user_action

logger = logging.getLogger(__name__)


def _int_id(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class SiteSponsorSync:
    """Periodic HTTPS pull of site-paid sponsors. Missing env keeps Boosty-only bots running."""

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
        if payload is None:
            return

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
