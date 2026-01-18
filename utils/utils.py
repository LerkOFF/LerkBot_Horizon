"""
Вспомогательные функции для бота.
Содержит общую логику, используемую в разных модулях.
"""
import discord
import logging
from typing import Optional
from config import TRACKED_ROLES, BOOSTY_ROLE_ID

logger = logging.getLogger(__name__)


def get_medal(position: int) -> str:
    """
    Получить эмодзи медали для позиции в топе.

    Args:
        position: позиция в топе (начиная с 1)

    Returns:
        Эмодзи медали или номер позиции
    """
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    return medals.get(position, f"{position}.")


def get_sponsor_roles(member: discord.Member) -> list[int]:
    """
    Получить список ID отслеживаемых ролей спонсора у пользователя.

    Args:
        member: участник Discord сервера

    Returns:
        Список ID ролей спонсора, которые есть у пользователя
    """
    member_role_ids = {role.id for role in member.roles}
    return [role_id for role_id in member_role_ids if role_id in TRACKED_ROLES]


async def manage_boosty_role(
    member: discord.Member,
    add: bool = True
) -> bool:
    """
    Добавить или удалить роль BOOSTY у пользователя.

    Args:
        member: участник Discord сервера
        add: True для добавления, False для удаления

    Returns:
        True если операция успешна, False в противном случае
    """
    boosty_role = member.guild.get_role(BOOSTY_ROLE_ID)
    if not boosty_role:
        logger.warning(f"Роль BOOSTY_ROLE_ID={BOOSTY_ROLE_ID} не найдена в гильдии {member.guild.name}")
        return False

    action = "добавлена" if add else "удалена"
    action_verb = "добавить" if add else "удалить"

    try:
        if add:
            await member.add_roles(boosty_role)
        else:
            await member.remove_roles(boosty_role)
        logger.info(f"BOOSTY_ROLE ({boosty_role.name}) {action} у пользователя {member.name}")
        return True
    except Exception as e:
        logger.error(f"Не удалось {action_verb} роль BOOSTY_ROLE: {e}")
        return False


async def send_error_response(
    ctx: discord.ApplicationContext,
    message: str,
    use_followup: bool = True
) -> None:
    """
    Отправить сообщение об ошибке пользователю.
    Пытается использовать followup, если не получается - respond.

    Args:
        ctx: контекст команды Discord
        message: текст сообщения
        use_followup: попробовать сначала followup
    """
    if use_followup:
        try:
            await ctx.followup.send(message, ephemeral=True)
            return
        except Exception:
            pass

    try:
        await ctx.respond(message, ephemeral=True)
    except Exception:
        logger.error(f"Не удалось отправить сообщение об ошибке: {message}")


def format_playtime(total_seconds: int) -> str:
    """
    Форматировать время игры в читаемый вид.

    Args:
        total_seconds: общее количество секунд

    Returns:
        Строка вида "X ч Y мин"
    """
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"
