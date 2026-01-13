import discord
from database import db
from logger import log_user_action
import logging

logger = logging.getLogger(__name__)


async def top_play_time(ctx: discord.ApplicationContext):
    """
    Команда для отображения топ-10 игроков по наигранному времени из БД SS14.
    Доступна всем пользователям.
    """
    try:
        # Откладываем ответ, так как запрос к БД может занять время
        await ctx.defer()

        # Получаем топ-10 игроков из БД
        top_players = await db.get_top_players_by_playtime(limit=10)

        if not top_players:
            await ctx.followup.send("Не удалось получить данные о наигранном времени или база данных пуста.")
            return

        # Формируем красивое сообщение с топом
        embed = discord.Embed(
            title="🏆 Топ-10 игроков по наигранному времени",
            description="Список игроков с наибольшим количеством наигранных часов",
            color=discord.Color.gold()
        )

        # Добавляем каждого игрока в embed
        for index, player in enumerate(top_players, start=1):
            player_name = player['user_name']
            total_time_seconds = player['total_time']

            # Конвертируем секунды в более читаемый формат (часы, минуты)
            hours = total_time_seconds // 3600
            minutes = (total_time_seconds % 3600) // 60

            # Эмодзи для топ-3
            if index == 1:
                medal = "🥇"
            elif index == 2:
                medal = "🥈"
            elif index == 3:
                medal = "🥉"
            else:
                medal = f"{index}."

            time_text = f"{hours} ч {minutes} мин" if hours > 0 else f"{minutes} мин"

            embed.add_field(
                name=f"{medal} {player_name}",
                value=f"⏱️ {time_text}",
                inline=False
            )

        # Отправляем embed
        await ctx.followup.send(embed=embed)
        log_user_action(f'Top play time command used', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды top_play_time: {e}")
        try:
            await ctx.followup.send(
                "Произошла ошибка при получении данных о наигранном времени. "
                "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                ephemeral=True
            )
        except:
            # Если followup не сработал, пробуем respond
            await ctx.respond(
                "Произошла ошибка при получении данных о наигранном времени. "
                "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                ephemeral=True
            )
        log_user_action(f'Error in top_play_time command: {e}', ctx.author)
