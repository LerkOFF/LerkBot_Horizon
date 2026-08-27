"""Keep a Discord channel name in sync with the SS14 server status."""

from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import tasks

from config import SS14_STATUS_CHANNEL_ID, SS14_STATUS_URL

logger = logging.getLogger(__name__)


def player_word(count: int) -> str:
    """Return the correct Russian form for a player count."""
    if count % 100 in range(11, 15):
        return "игроков"
    if count % 10 == 1:
        return "игрок"
    if count % 10 in range(2, 5):
        return "игрока"
    return "игроков"


def online_channel_name(players: int) -> str:
    return f"🟢 Сервер онлайн • {players} {player_word(players)}"


class ServerStatusMonitor:
    """Poll the SS14 status endpoint and update one Discord channel."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    def start(self) -> None:
        if not self.update_status.is_running():
            self.update_status.start()

    def stop(self) -> None:
        if self.update_status.is_running():
            self.update_status.cancel()

    @tasks.loop(minutes=5)
    async def update_status(self) -> None:
        players = await self._fetch_players()
        name = online_channel_name(players) if players is not None else "🔴 Сервер офлайн"
        await self._rename_channel(name)

    @update_status.before_loop
    async def before_update(self) -> None:
        await self.bot.wait_until_ready()

    async def _fetch_players(self) -> int | None:
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(SS14_STATUS_URL, headers={"Accept": "application/json"}) as response:
                    if response.status != 200:
                        logger.warning("SS14 status API ответил %s", response.status)
                        return None
                    payload = await response.json()
                    players = payload.get("players") if isinstance(payload, dict) else None
                    if isinstance(players, bool) or not isinstance(players, int) or players < 0:
                        logger.warning("SS14 status API вернул некорректное число игроков: %r", players)
                        return None
                    return players
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.warning("SS14 сервер недоступен: %s", exc)
            return None

    async def _rename_channel(self, name: str) -> None:
        channel = self.bot.get_channel(SS14_STATUS_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(SS14_STATUS_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                logger.error("Не удалось получить status-канал %s: %s", SS14_STATUS_CHANNEL_ID, exc)
                return

        if channel.name == name:
            return

        try:
            await channel.edit(name=name, reason="Обновление статуса сервера SS14")
            logger.info("Status-канал переименован: %s", name)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error("Не удалось переименовать status-канал %s: %s", SS14_STATUS_CHANNEL_ID, exc)
