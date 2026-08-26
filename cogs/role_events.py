import discord
import logging
from config import TRACKED_ROLES, INFO_CHANNEL_ID, CKEY_CHANNEL_ID
from services.sponsors_file import remove_sponsor
from utils.logger import log_user_action
from utils.utils import manage_boosty_role

logger = logging.getLogger(__name__)

# While the site sync cog changes roles, skip Boosty DMs and file writes from this handler.
skip_role_events = False


async def _handle_role_added(member: discord.Member, role: discord.Role) -> None:
    """Обработка добавления роли спонсора."""
    # Отправка личного сообщения
    try:
        await member.send(f"Спасибо, что подписались на бусти! Теперь вы {role.name}.")
    except discord.Forbidden:
        logger.warning(f"Не удалось отправить личное сообщение пользователю {member.name}. Личные сообщения отключены.")

    # Сообщение в канале
    ckey_channel = member.guild.get_channel(CKEY_CHANNEL_ID)
    if ckey_channel:
        await ckey_channel.send(
            f"Привет, {member.mention}! Ты стал спонсором с доступом к донат-магазину, "
            "если хочешь получить доступ к нему в игре - используй команду **/my_ckey**"
        )

    # Добавление роли BOOSTY
    if await manage_boosty_role(member, add=True):
        log_user_action(f"BOOSTY_ROLE добавлена пользователю", member)

    log_user_action(f"Role added: {role.id}", member)


async def _handle_role_removed(member: discord.Member, role: discord.Role) -> None:
    """Обработка удаления роли спонсора."""
    # Отправка уведомления
    try:
        await member.send(
            f"Видимо Ваша подписка на бусти **https://boosty.to/ss14.starhorizon** закончилась, "
            f"так как вы потеряли роль: {role.name}."
        )
    except discord.Forbidden:
        info_channel = member.guild.get_channel(INFO_CHANNEL_ID)
        if info_channel:
            await info_channel.send(f"{member.mention}, Ваша подписка закончилась.")

    # Удаление из файла спонсоров
    await remove_sponsor(member.name)

    # Удаление роли BOOSTY
    if await manage_boosty_role(member, add=False):
        log_user_action(f"BOOSTY_ROLE удалена у пользователя", member)

    log_user_action(f"Role removed: {role.id}", member)


async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    """Обработчик события изменения ролей участника."""
    if skip_role_events:
        return

    # Проверка добавленных ролей
    added_roles = set(after.roles) - set(before.roles)
    added_tracked = [role for role in added_roles if role.id in TRACKED_ROLES]

    if added_tracked:
        await _handle_role_added(after, added_tracked[0])

    # Проверка удалённых ролей
    removed_roles = set(before.roles) - set(after.roles)
    removed_tracked = [role for role in removed_roles if role.id in TRACKED_ROLES]

    if removed_tracked:
        await _handle_role_removed(after, removed_tracked[0])
