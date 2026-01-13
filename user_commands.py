from datetime import datetime
import discord
from config import CKEY_CHANNEL_ID, SPONSORS_FILE_PATH, CAN_GIVES_ROLES, DISPOSABLE_FILE_PATH
import re
from logger import log_user_action
from utils import get_sponsor_roles

# Константы
DEFAULT_COLOR = "#FF0000"
CKEY_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
HEX_COLOR_PATTERN = re.compile(r'^#([A-Fa-f0-9]{6})$')


async def check_ckey_channel(ctx: discord.ApplicationContext) -> bool:
    """
    Проверить, что команда вызвана в правильном канале.

    Returns:
        True если канал корректный, False если нет (ответ уже отправлен)
    """
    ckey_channel = ctx.guild.get_channel(CKEY_CHANNEL_ID)
    if ckey_channel is None:
        await ctx.respond("Ошибка: указанный канал для команды не найден.", ephemeral=True)
        return False

    if ctx.channel.id != CKEY_CHANNEL_ID:
        await ctx.respond(f"Эта команда может использоваться только в канале {ckey_channel.mention}.", ephemeral=True)
        return False

    return True


async def check_is_sponsor(ctx: discord.ApplicationContext) -> list[int] | None:
    """
    Проверить, является ли пользователь спонсором.

    Returns:
        Список ID ролей спонсора или None (если не спонсор, ответ уже отправлен)
    """
    tracked_roles = get_sponsor_roles(ctx.author)
    if not tracked_roles:
        await ctx.respond("Вы не спонсор.", ephemeral=True)
        return None
    return tracked_roles


def update_disposable_file(old_ckey: str, new_ckey: str) -> None:
    """
    Обновить ckey в файле disposable.

    Args:
        old_ckey: старый сикей для поиска
        new_ckey: новый сикей для замены
    """
    try:
        with open(DISPOSABLE_FILE_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return

    updated_lines = []
    for line in lines:
        parts = line.strip().split(', ')
        if parts and parts[0] == old_ckey:
            # Формат: "ckey, slots, tokens"
            slots = parts[1] if len(parts) >= 2 else "0"
            tokens = parts[2] if len(parts) >= 3 else "0"
            updated_lines.append(f"{new_ckey}, {slots}, {tokens}\n")
        else:
            updated_lines.append(line)

    with open(DISPOSABLE_FILE_PATH, 'w', encoding='utf-8') as f:
        f.writelines(updated_lines)


def read_sponsors_file() -> list[str]:
    """Прочитать файл спонсоров."""
    try:
        with open(SPONSORS_FILE_PATH, 'r', encoding='utf-8') as f:
            return f.readlines()
    except FileNotFoundError:
        return []


def write_sponsors_file(lines: list[str]) -> None:
    """Записать файл спонсоров."""
    with open(SPONSORS_FILE_PATH, 'w', encoding='utf-8') as f:
        f.writelines(lines)


async def my_ckey(ctx: discord.ApplicationContext, ckey: discord.Option(str, "Ваш сикей в игре")):
    """Команда для установки сикея пользователя."""
    try:
        if not await check_ckey_channel(ctx):
            return

        if not CKEY_PATTERN.match(ckey):
            await ctx.respond("Сикей должен содержать только английские буквы, цифры или подчеркивания.")
            return

        tracked_roles = await check_is_sponsor(ctx)
        if tracked_roles is None:
            return

        member = ctx.author
        time_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_record = f"{member.name}, {ckey}, {tracked_roles[0]}, {time_now}, {DEFAULT_COLOR}\n"

        lines = read_sponsors_file()

        old_ckey = None
        updated_lines = []
        updated = False

        for line in lines:
            if line.startswith(f"{member.name},"):
                old_ckey = line.split(', ')[1]
                updated_lines.append(new_record)
                updated = True
            else:
                updated_lines.append(line)

        if not updated:
            updated_lines.append(new_record)

        write_sponsors_file(updated_lines)

        # Обновление ckey в DISPOSABLE_FILE_PATH, если найден старый
        if old_ckey:
            update_disposable_file(old_ckey, ckey)

        await ctx.respond(f'Сикей "{ckey}" был установлен для спонсорского магазина в игре.')
        log_user_action(f'CKEY command used: {ckey} (default color: {DEFAULT_COLOR})', member)

    except Exception as e:
        await ctx.respond(f"Произошла ошибка: {e}", ephemeral=True)
        log_user_action(f'Error updating CKEY: {e}', ctx.author)
        raise


async def change_my_name_color(ctx: discord.ApplicationContext, color_hex: discord.Option(str, "HEX-код цвета")):
    """Команда для изменения цвета имени пользователя."""
    try:
        if not await check_ckey_channel(ctx):
            return

        if not HEX_COLOR_PATTERN.match(color_hex):
            await ctx.respond("Неверный формат HEX-кода. Используйте формат #RRGGBB.", ephemeral=True)
            return

        if await check_is_sponsor(ctx) is None:
            return

        member = ctx.author
        lines = read_sponsors_file()

        if not lines:
            await ctx.respond("Файл спонсоров не найден. Пожалуйста, сначала используйте команду /my_ckey.", ephemeral=True)
            return

        sponsor_found = False
        updated_lines = []

        for line in lines:
            if line.startswith(f"{member.name},"):
                sponsor_found = True
                parts = line.strip().split(', ')
                if len(parts) >= 5:
                    parts[4] = color_hex
                else:
                    parts.append(color_hex)
                updated_lines.append(', '.join(parts) + '\n')
            else:
                updated_lines.append(line)

        if not sponsor_found:
            await ctx.respond("Ваша запись не найдена. Пожалуйста, сначала используйте команду /my_ckey.", ephemeral=True)
            return

        write_sponsors_file(updated_lines)

        await ctx.respond(f"Цвет вашего имени успешно изменён на {color_hex}.")
        log_user_action(f'Change color command used: {color_hex}', member)

    except Exception as e:
        await ctx.respond(f"Произошла ошибка при изменении цвета имени: {e}", ephemeral=True)
        log_user_action(f'Error changing color: {e}', ctx.author)


async def add_disposable(
    ctx: discord.ApplicationContext,
    ds_nickname: discord.Option(str, "Дискорд никнейм пользователя"),
    slots: discord.Option(int, "Количество слотов"),
    tokens: discord.Option(int, "Количество токенов")
):
    """Команда для добавления слотов и токенов пользователю."""
    try:
        if ctx.author.name not in CAN_GIVES_ROLES:
            await ctx.respond("У вас нет прав на выполнение этой команды.", ephemeral=True)
            return

        # Поиск ckey по ds_nickname в SPONSORS_FILE_PATH
        ckey = None
        lines = read_sponsors_file()
        for line in lines:
            parts = line.split(', ')
            if parts[0] == ds_nickname:
                ckey = parts[1]
                break

        if not ckey:
            await ctx.respond(
                f"Пользователь с дискорд ником '{ds_nickname}' не найден в списке спонсоров. "
                "Сначала используйте команду /my_ckey.",
                ephemeral=True
            )
            return

        # Чтение и обновление DISPOSABLE_FILE_PATH
        try:
            with open(DISPOSABLE_FILE_PATH, 'r', encoding='utf-8') as f:
                disposable_lines = f.readlines()
        except FileNotFoundError:
            disposable_lines = []

        record_updated = False
        updated_lines = []

        for line in disposable_lines:
            parts = line.strip().split(', ')
            if parts and parts[0] == ckey:
                updated_lines.append(f"{ckey}, {slots}, {tokens}\n")
                record_updated = True
            else:
                updated_lines.append(line)

        if not record_updated:
            updated_lines.append(f"{ckey}, {slots}, {tokens}\n")

        with open(DISPOSABLE_FILE_PATH, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)

        await ctx.respond(
            f"Для '{ds_nickname}' ({ckey}) было добавлено/обновлено '{slots}' слотов и '{tokens}' токенов.",
            ephemeral=True
        )
        log_user_action(f'Disposable slots/tokens added/updated: {slots} slots, {tokens} tokens to {ckey}', ctx.author)

    except Exception as e:
        await ctx.respond(f"Произошла ошибка при добавлении слотов и токенов: {e}", ephemeral=True)
        log_user_action(f'Error adding disposable slots/tokens: {e}', ctx.author)
