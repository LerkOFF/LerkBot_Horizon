import discord
import asyncio
import logging
import os
import tempfile
from config import TRACKED_ROLES, INFO_CHANNEL_ID, SPONSORS_FILE_PATH, CKEY_CHANNEL_ID
from utils.logger import log_user_action
from utils.utils import manage_boosty_role

logger = logging.getLogger(__name__)

# Блокировка для безопасной записи в файл спонсоров
_sponsors_file_lock = asyncio.Lock()


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
    await _remove_sponsor_from_file(member.name)

    # Удаление роли BOOSTY
    if await manage_boosty_role(member, add=False):
        log_user_action(f"BOOSTY_ROLE удалена у пользователя", member)

    log_user_action(f"Role removed: {role.id}", member)


async def _remove_sponsor_from_file(username: str) -> None:
    """Атомарное удаление пользователя из файла спонсоров."""
    async with _sponsors_file_lock:
        try:
            try:
                with open(SPONSORS_FILE_PATH, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except FileNotFoundError:
                logger.warning(f"Файл спонсоров {SPONSORS_FILE_PATH} не найден")
                return

            # Фильтрация строк (удаление пользователя)
            filtered_lines = [line for line in lines if not line.startswith(f"{username},")]

            # Атомарная запись через временный файл
            temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(SPONSORS_FILE_PATH), text=True)
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    f.writelines(filtered_lines)
                os.replace(temp_path, SPONSORS_FILE_PATH)
                logger.info(f"Пользователь {username} удалён из файла спонсоров")
            except Exception as e:
                logger.error(f"Ошибка при записи файла спонсоров: {e}")
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

        except Exception as e:
            logger.error(f"Ошибка при обработке файла спонсоров: {e}")


async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    """Обработчик события изменения ролей участника."""
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
