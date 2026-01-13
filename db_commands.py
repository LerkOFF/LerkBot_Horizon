import discord
from database import db
from logger import log_user_action
from utils import get_medal, send_error_response, format_playtime
from config import TOP_COMMANDS_ALLOWED_CHANNELS
import logging

logger = logging.getLogger(__name__)


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
    Команда для отображения топ-10 игроков по банковскому балансу из БД SS14.
    """
    if not await check_top_commands_channel(ctx):
        return
    
    try:
        await ctx.defer()

        top_players = await db.get_top_players_by_balance(limit=10)

        if not top_players:
            await ctx.followup.send("Не удалось получить данные о балансе или база данных пуста.")
            return

        embed = discord.Embed(
            title="💰 Топ-10 игроков по банковскому балансу",
            description="Список игроков с наибольшим количеством денег на счету",
            color=discord.Color.green()
        )

        for index, player in enumerate(top_players, start=1):
            user_name = player['user_name']
            char_name = player['char_name']
            bank_balance = player['bank_balance']

            medal = get_medal(index)
            balance_text = f"{bank_balance:,.0f}" if bank_balance else "0"

            embed.add_field(
                name=f"{medal} {user_name}",
                value=f"👤 {char_name}\n💵 {balance_text} кредитов",
                inline=False
            )

        await ctx.followup.send(embed=embed)
        log_user_action('Top balance command used', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды top_balance: {e}")
        await send_error_response(
            ctx,
            "Произошла ошибка при получении данных о балансе. "
            "Пожалуйста, попробуйте позже или обратитесь к администратору."
        )
        log_user_action(f'Error in top_balance command: {e}', ctx.author)
