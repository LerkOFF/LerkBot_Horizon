"""One-shot Discord → site forum import. Does not start sponsor or status sync.

Stop the running bot first: two processes cannot share DISCORD_TOKEN.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import discord

from cogs import forum_sync as forum_sync_mod
from cogs.forum_sync import ForumSync
from config import GUILD_IDS, TOKEN

only = sys.argv[1:]
if only:
    forum_sync_mod.FORUM_CHANNEL_IDS = frozenset(int(x) for x in only)
    print("channels", list(forum_sync_mod.FORUM_CHANNEL_IDS))

probe = ForumSync(discord.Bot())
if not probe.enabled():
    sys.exit("Зеркало выключено: нет SITE_SPONSORS_URL или SPONSOR_SYNC_TOKEN")

asyncio.set_event_loop(asyncio.new_event_loop())

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

bot = discord.Bot(intents=intents)
sync = ForumSync(bot)


@bot.event
async def on_ready() -> None:
    print("ready", str(bot.user), "guilds", len(bot.guilds))
    guild = bot.get_guild(GUILD_IDS[0]) if GUILD_IDS else None
    if guild is None and bot.guilds:
        guild = bot.guilds[0]
    print("guild", getattr(guild, "name", None), getattr(guild, "id", None))
    stats = await sync.import_guild(guild)
    print("STATS", stats)
    await bot.close()


bot.run(TOKEN)
