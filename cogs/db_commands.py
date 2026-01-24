import discord
from database import db
from utils.logger import log_user_action
from utils.utils import get_medal, send_error_response, format_playtime
from config import TOP_COMMANDS_ALLOWED_CHANNELS
import logging

logger = logging.getLogger(__name__)

PAGE_SIZE = 10


async def check_top_commands_channel(ctx: discord.ApplicationContext) -> bool:
    """
    Проверить, что команда вызвана в разрешенном канале.

    Returns:
        True если канал разрешен, False если нет (ответ уже отправлен)
    """
    if ctx.channel.id not in TOP_COMMANDS_ALLOWED_CHANNELS:
        allowed_channels = [ctx.guild.get_channel(ch_id) for ch_id in TOP_COMMANDS_ALLOWED_CHANNELS]
        allowed_channels = [ch for ch in allowed_channels if ch is not None]
        
        if not allowed_channels:
            await ctx.respond("Ошибка: разрешенные каналы для команды не найдены.", ephemeral=True)
            return False
        
        channels_mention = ", ".join([ch.mention for ch in allowed_channels])
        await ctx.respond(
            f"Эта команда может использоваться только в следующих каналах: {channels_mention}.",
            ephemeral=True
        )
        return False

    return True


def _build_balance_embed(
    players: list,
    page: int,
    total_pages: int,
    total_count: int,
) -> discord.Embed:
    """Собрать embed для одной страницы топа по балансу."""
    embed = discord.Embed(
        title="💰 Топ игроков по банковскому балансу",
        description="Список игроков с наибольшим количеством денег на счету. Листайте страницы кнопками.",
        color=discord.Color.green(),
    )
    start_rank = page * PAGE_SIZE
    for i, player in enumerate(players):
        rank = start_rank + i + 1
        user_name = player["user_name"]
        char_name = player["char_name"]
        bank_balance = player["bank_balance"]
        medal = get_medal(rank)
        balance_text = f"{bank_balance:,.0f}" if bank_balance else "0"
        embed.add_field(
            name=f"{medal} {user_name}",
            value=f"👤 {char_name}\n💵 {balance_text} кредитов",
            inline=False,
        )
    embed.set_footer(text=f"Страница {page + 1} из {total_pages} • Всего игроков: {total_count}")
    return embed


class TopBalanceView(discord.ui.View):
    """View с кнопками пагинации для топа по балансу."""

    def __init__(self, total_count: int, *, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.total_count = total_count
        self.total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
        self.current_page = 0
        self._prev = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="◀ Назад",
            custom_id="top_balance_prev",
            disabled=True,
        )
        self._next = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Вперёд ▶",
            custom_id="top_balance_next",
            disabled=self.total_pages <= 1,
        )
        self._prev.callback = self._on_prev
        self._next.callback = self._on_next
        self.add_item(self._prev)
        self.add_item(self._next)

    def _update_buttons(self) -> None:
        self._prev.disabled = self.current_page <= 0
        self._next.disabled = self.current_page >= self.total_pages - 1

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self.current_page <= 0:
            return
        self.current_page -= 1
        await self._refresh(interaction)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if self.current_page >= self.total_pages - 1:
            return
        self.current_page += 1
        await self._refresh(interaction)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(invisible=True)
        try:
            offset = self.current_page * PAGE_SIZE
            players = await db.get_top_players_by_balance(limit=PAGE_SIZE, offset=offset)
            embed = _build_balance_embed(
                players, self.current_page, self.total_pages, self.total_count
            )
            self._update_buttons()
            await interaction.message.edit(embed=embed, view=self)
        except Exception as e:
            logger.error(f"Ошибка при загрузке страницы топа по балансу: {e}")
            self._update_buttons()
            for item in self.children:
                item.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except Exception:
            pass


async def top_play_time(ctx: discord.ApplicationContext):
    """
    Команда для отображения топ-10 игроков по наигранному времени из БД SS14.
    """
    if not await check_top_commands_channel(ctx):
        return
    
    try:
        await ctx.defer()

        top_players = await db.get_top_players_by_playtime(limit=10)

        if not top_players:
            await ctx.followup.send("Не удалось получить данные о наигранном времени или база данных пуста.")
            return

        embed = discord.Embed(
            title="🏆 Топ-10 игроков по наигранному времени",
            description="Список игроков с наибольшим количеством наигранных часов",
            color=discord.Color.gold()
        )

        for index, player in enumerate(top_players, start=1):
            player_name = player['user_name']
            total_time = player['total_time']

            # Обрабатываем timedelta или числовое значение
            if hasattr(total_time, 'total_seconds'):
                total_time_seconds = int(total_time.total_seconds())
            else:
                total_time_seconds = int(total_time)

            medal = get_medal(index)
            time_text = format_playtime(total_time_seconds)

            embed.add_field(
                name=f"{medal} {player_name}",
                value=f"⏱️ {time_text}",
                inline=False
            )

        await ctx.followup.send(embed=embed)
        log_user_action('Top play time command used', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды top_play_time: {e}")
        await send_error_response(
            ctx,
            "Произошла ошибка при получении данных о наигранном времени. "
            "Пожалуйста, попробуйте позже или обратитесь к администратору."
        )
        log_user_action(f'Error in top_play_time command: {e}', ctx.author)


async def top_balance(ctx: discord.ApplicationContext):
    """
    Команда для отображения всех игроков по банковскому балансу из БД SS14.
    Пагинация по 10 человек на страницу, листание кнопками «Назад» / «Вперёд».
    """
    if not await check_top_commands_channel(ctx):
        return

    try:
        await ctx.defer()

        total_count = await db.get_top_players_by_balance_count()
        if total_count == 0:
            await ctx.followup.send("Не удалось получить данные о балансе или база данных пуста.")
            return

        players = await db.get_top_players_by_balance(limit=PAGE_SIZE, offset=0)
        embed = _build_balance_embed(players, 0, max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE), total_count)
        view = TopBalanceView(total_count=total_count)
        msg = await ctx.followup.send(embed=embed, view=view)
        view.message = msg
        log_user_action("Top balance command used", ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды top_balance: {e}")
        await send_error_response(
            ctx,
            "Произошла ошибка при получении данных о балансе. "
            "Пожалуйста, попробуйте позже или обратитесь к администратору.",
        )
        log_user_action(f"Error in top_balance command: {e}", ctx.author)
