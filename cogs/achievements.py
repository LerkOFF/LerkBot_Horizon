"""
Cog для управления достижениями игроков SS14 через Discord команды.
"""
import discord
import logging
import tempfile
from pathlib import Path
from database import db
from services.achievements_catalog import catalog, ACHIEVEMENT_ID_PATTERN
from services.player_achievements_store import store
from config import ACHIEVEMENTS_ALLOWED_ROLE_IDS, ACHIEVEMENTS_CATALOG_PATH
from utils.logger import log_user_action

logger = logging.getLogger(__name__)


class CkeyInputModal(discord.ui.Modal):
    """Модальное окно для ввода ckey игрока."""

    def __init__(self, ds_nickname: str):
        """
        Инициализация модального окна.

        Args:
            ds_nickname: Discord никнейм игрока
        """
        super().__init__(title="Ввод ckey игрока")
        self.ds_nickname = ds_nickname
        self.ckey_input = discord.ui.InputText(
            label="Ckey игрока",
            placeholder="Введите ckey игрока в игре (например: joulerk)",
            min_length=1,
            max_length=50
        )
        self.add_item(self.ckey_input)

    async def callback(self, interaction: discord.Interaction):
        """
        Обработчик отправки модального окна.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        ckey = self.ckey_input.value.strip()

        if not ckey:
            await interaction.response.send_message(
                "Ckey не может быть пустым.",
                ephemeral=True
            )
            return

        # Нормализация ckey
        ckey = ckey.lower().strip()

        try:
            # Проверка ckey в БД SS14
            ckey_from_db = await db.resolve_ckey_by_player_name(ckey)

            if not ckey_from_db:
                await interaction.response.send_message(
                    f"❌ Ckey '{ckey}' не найден в базе данных SS14.",
                    ephemeral=True
                )
                return

            # Используем нормализованный ckey из БД
            ckey = ckey_from_db

            # Получение текущих достижений игрока
            current_achievements = await store.get_player_achievements(ckey)
            if current_achievements is None:
                # Игрок не в файле - создаем запись с пустым списком достижений
                await store.upsert_player(ckey, self.ds_nickname, set())
                current_achievements = set()
                logger.info(f"Создана новая запись для игрока {self.ds_nickname} ({ckey})")

            # Получение всех доступных достижений из каталога
            catalog_all = catalog.get_all()

            # Вычисление доступных достижений (не имеющиеся у игрока)
            available_achievements = {
                ach_id: (ach_def.title, ach_def.description)
                for ach_id, ach_def in catalog_all.items()
                if ach_id not in current_achievements
            }

            if not available_achievements:
                await interaction.response.send_message(
                    f"Игрок **{self.ds_nickname}** ({ckey}) уже имеет все достижения.",
                    ephemeral=True
                )
                return

            # Создание view с dropdown меню
            view = AchievementSelectView(ckey, self.ds_nickname, available_achievements)

            await interaction.response.send_message(
                f"Выберите достижение для выдачи игроку **{self.ds_nickname}** ({ckey}):",
                view=view,
                ephemeral=True
            )

            log_user_action(f'Set reach command: ckey {ckey} for {self.ds_nickname}', interaction.user)

        except Exception as e:
            logger.error(f"Ошибка при выдаче достижения игроку {self.ds_nickname} ({ckey}): {e}")
            await interaction.response.send_message(
                f"Произошла ошибка при выдаче достижения: {e}",
                ephemeral=True
            )


class AchievementSelectView(discord.ui.View):
    """View с dropdown меню для выбора достижения."""

    def __init__(self, ckey: str, ds_nickname: str, available_achievements: dict[str, tuple[str, str]]):
        """
        Инициализация view.

        Args:
            ckey: ckey игрока
            ds_nickname: Discord никнейм игрока
            available_achievements: словарь {ach_id: (title, description)} доступных достижений
        """
        super().__init__(timeout=120)  # View истекает через 120 секунд
        self.ckey = ckey
        self.ds_nickname = ds_nickname
        self.available_achievements = available_achievements

        # Создание dropdown с достижениями
        if available_achievements:
            select = discord.ui.Select(
                placeholder="Выберите достижение для выдачи",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=title,
                        value=ach_id,
                        description=description[:100] if description else title[:100]  # Discord ограничение длины описания
                    )
                    for ach_id, (title, description) in available_achievements.items()
                ]
            )
            select.callback = self.on_select
            self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        """
        Обработчик выбора достижения из dropdown.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        selected_ach_id = interaction.data['values'][0]

        try:
            # Откладываем ответ для выполнения асинхронных операций
            await interaction.response.defer(ephemeral=True)

            # Проверяем состояние хранилища еще раз
            current_achievements = await store.get_player_achievements(self.ckey)

            if current_achievements and selected_ach_id in current_achievements:
                ach_info = self.available_achievements.get(selected_ach_id)
                ach_title = ach_info[0] if ach_info else selected_ach_id
                # Редактируем исходное сообщение с dropdown
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Достижение '{ach_title}' уже выдано игроку {self.ds_nickname}.",
                    view=None  # Убираем dropdown
                )
                return

            # Добавляем достижение
            success = await store.add_achievement(self.ckey, self.ds_nickname, selected_ach_id)

            if success:
                ach_info = self.available_achievements.get(selected_ach_id)
                ach_title = ach_info[0] if ach_info else selected_ach_id
                # Редактируем исходное сообщение с dropdown, заменяя его на текст о выдаче
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"✅ Достижение **{ach_title}** выдано игроку **{self.ds_nickname}** ({self.ckey}).",
                    view=None  # Убираем dropdown
                )
                log_user_action(
                    f'Achievement granted: {selected_ach_id} to {self.ds_nickname} ({self.ckey})',
                    interaction.user
                )
            else:
                ach_info = self.available_achievements.get(selected_ach_id)
                ach_title = ach_info[0] if ach_info else selected_ach_id
                # Редактируем исходное сообщение
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Достижение '{ach_title}' уже было выдано игроку {self.ds_nickname}.",
                    view=None  # Убираем dropdown
                )

        except Exception as e:
            logger.error(f"Ошибка при выдаче достижения {selected_ach_id} игроку {self.ckey}: {e}")
            try:
                # Пытаемся отредактировать сообщение с ошибкой
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Произошла ошибка при выдаче достижения: {e}",
                    view=None
                )
            except Exception:
                # Если редактирование не удалось, отправляем новое сообщение
                try:
                    await interaction.followup.send(
                        f"Произошла ошибка при выдаче достижения: {e}",
                        ephemeral=True
                    )
                except Exception:
                    pass

    async def on_timeout(self):
        """Обработчик истечения времени ожидания."""
        for item in self.children:
            item.disabled = True


class RemoveAchievementSelectView(discord.ui.View):
    """View с dropdown меню для выбора достижения для удаления."""

    def __init__(self, ckey: str, ds_nickname: str, player_achievements: dict[str, str]):
        """
        Инициализация view.

        Args:
            ckey: ckey игрока
            ds_nickname: Discord никнейм игрока
            player_achievements: словарь {ach_id: title} достижений игрока
        """
        super().__init__(timeout=120)  # View истекает через 120 секунд
        self.ckey = ckey
        self.ds_nickname = ds_nickname
        self.player_achievements = player_achievements

        # Создание dropdown с достижениями
        if player_achievements:
            select = discord.ui.Select(
                placeholder="Выберите достижение для удаления",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=title,
                        value=ach_id,
                        description=title[:100]  # Discord ограничение длины описания
                    )
                    for ach_id, title in player_achievements.items()
                ]
            )
            select.callback = self.on_select
            self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        """
        Обработчик выбора достижения из dropdown.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        selected_ach_id = interaction.data['values'][0]

        try:
            # Откладываем ответ для выполнения асинхронных операций
            await interaction.response.defer(ephemeral=True)

            # Проверяем состояние хранилища еще раз
            current_achievements = await store.get_player_achievements(self.ckey)

            if not current_achievements or selected_ach_id not in current_achievements:
                ach_title = self.player_achievements.get(selected_ach_id, selected_ach_id)
                # Редактируем исходное сообщение с dropdown
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Достижение '{ach_title}' не найдено у игрока {self.ds_nickname}.",
                    view=None  # Убираем dropdown
                )
                return

            # Удаляем достижение
            success = await store.remove_achievement(self.ckey, self.ds_nickname, selected_ach_id)

            if success:
                ach_title = self.player_achievements.get(selected_ach_id, selected_ach_id)
                # Редактируем исходное сообщение с dropdown, заменяя его на текст об удалении
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"✅ Достижение **{ach_title}** удалено у игрока **{self.ds_nickname}** ({self.ckey}).",
                    view=None  # Убираем dropdown
                )
                log_user_action(
                    f'Achievement removed: {selected_ach_id} from {self.ds_nickname} ({self.ckey})',
                    interaction.user
                )
            else:
                ach_title = self.player_achievements.get(selected_ach_id, selected_ach_id)
                # Редактируем исходное сообщение
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Достижение '{ach_title}' не было у игрока {self.ds_nickname}.",
                    view=None  # Убираем dropdown
                )

        except Exception as e:
            logger.error(f"Ошибка при удалении достижения {selected_ach_id} у игрока {self.ckey}: {e}")
            try:
                # Пытаемся отредактировать сообщение с ошибкой
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Произошла ошибка при удалении достижения: {e}",
                    view=None
                )
            except Exception:
                # Если редактирование не удалось, отправляем новое сообщение
                try:
                    await interaction.followup.send(
                        f"Произошла ошибка при удалении достижения: {e}",
                        ephemeral=True
                    )
                except Exception:
                    pass

    async def on_timeout(self):
        """Обработчик истечения времени ожидания."""
        for item in self.children:
            item.disabled = True


async def get_reachs(
    ctx: discord.ApplicationContext,
    user: discord.Option(discord.Member, "Пользователь Discord (можно использовать @пользователь)", required=False, default=None)
):
    """
    Команда для получения списка достижений игрока.

    Args:
        ctx: контекст команды Discord
        user: пользователь Discord (можно использовать пинг @пользователь)
    """
    try:
        await ctx.defer()

        # Получение Discord никнейма
        if user:
            # Если передан пинг пользователя - используем его никнейм
            discord_nickname = user.display_name or user.name
        else:
            # Если пинг не передан - используем никнейм автора команды
            discord_nickname = ctx.author.display_name or ctx.author.name

        if not discord_nickname:
            await ctx.followup.send("Не удалось определить Discord никнейм.", ephemeral=True)
            return

        # Получение достижений игрока по Discord никнейму
        result = await store.get_player_achievements_by_discord_nickname(discord_nickname)

        if not result:
            await ctx.followup.send(
                f"У игрока с Discord никнеймом '{discord_nickname}' не найдено достижений.",
                ephemeral=True
            )
            return

        ckey, achievements_set = result

        if not achievements_set or len(achievements_set) == 0:
            await ctx.followup.send(f"Игрок **{discord_nickname}** ({ckey}) не имеет достижений.")
            return

        # Получение каталога достижений
        catalog_all = catalog.get_all()

        # Формирование списка достижений
        achievements_list = []
        unknown_achievements = []

        for ach_id in sorted(achievements_set):
            ach_def = catalog_all.get(ach_id)
            if ach_def:
                achievements_list.append(f"• **{ach_def.title}** — {ach_def.description}")
            else:
                unknown_achievements.append(ach_id)
                logger.warning(f"Неизвестное достижение '{ach_id}' найдено у игрока {ckey}")

        # Формирование ответа
        embed = discord.Embed(
            title=f"🏆 Достижения игрока {discord_nickname}",
            description=f"**Ckey:** {ckey}",
            color=discord.Color.gold()
        )

        if achievements_list:
            achievements_text = "\n".join(achievements_list)
            # Discord ограничение на длину поля embed (1024 символа)
            if len(achievements_text) > 1024:
                achievements_text = achievements_text[:1020] + "..."
            embed.add_field(name="Достижения", value=achievements_text, inline=False)

        if unknown_achievements:
            unknown_text = ", ".join(unknown_achievements)
            embed.add_field(
                name="⚠️ Неизвестные достижения",
                value=f"*{unknown_text}*",
                inline=False
            )

        await ctx.followup.send(embed=embed)
        log_user_action(f'Get reachs command used: {discord_nickname} ({ckey})', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды get_reachs для '{discord_nickname}': {e}")
        await ctx.followup.send(
            "Произошла ошибка при получении достижений. Пожалуйста, попробуйте позже.",
            ephemeral=True
        )


async def set_reach(
    ctx: discord.ApplicationContext,
    user: discord.Option(discord.Member, "Пользователь Discord (можно использовать @пользователь)", required=False, default=None)
):
    """
    Команда для выдачи достижения игроку через dropdown меню.

    Args:
        ctx: контекст команды Discord
        user: пользователь Discord (можно использовать пинг @пользователь)
    """
    try:
        # Проверка прав
        user_roles = {role.id for role in ctx.author.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await ctx.respond(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Получение Discord никнейма
        if user:
            # Если передан пинг пользователя - используем его никнейм
            discord_nickname = user.display_name or user.name
        else:
            # Если пинг не передан - используем никнейм автора команды
            discord_nickname = ctx.author.display_name or ctx.author.name

        if not discord_nickname:
            await ctx.respond("Не удалось определить Discord никнейм.", ephemeral=True)
            return

        # Пытаемся найти игрока по Discord нику в файле
        result = await store.get_player_achievements_by_discord_nickname(discord_nickname)

        if result:
            # Игрок найден в файле - используем его ckey и показываем dropdown сразу
            ckey, current_achievements = result

            await ctx.defer(ephemeral=True)

            # Проверяем ckey в БД SS14 для валидации
            ckey_from_db = await db.resolve_ckey_by_player_name(ckey)

            if not ckey_from_db:
                await ctx.followup.send(
                    f"❌ Ckey '{ckey}' игрока '{discord_nickname}' не найден в базе данных SS14. "
                    "Пожалуйста, проверьте правильность данных.",
                    ephemeral=True
                )
                return

            # Используем нормализованный ckey из БД
            ckey = ckey_from_db

            # Получение всех доступных достижений из каталога
            catalog_all = catalog.get_all()

            # Вычисление доступных достижений (не имеющиеся у игрока)
            available_achievements = {
                ach_id: (ach_def.title, ach_def.description)
                for ach_id, ach_def in catalog_all.items()
                if ach_id not in current_achievements
            }

            if not available_achievements:
                await ctx.followup.send(
                    f"Игрок **{discord_nickname}** ({ckey}) уже имеет все достижения.",
                    ephemeral=True
                )
                return

            # Создание view с dropdown меню
            view = AchievementSelectView(ckey, discord_nickname, available_achievements)

            await ctx.followup.send(
                f"Выберите достижение для выдачи игроку **{discord_nickname}** ({ckey}):",
                view=view,
                ephemeral=True
            )

            log_user_action(f'Set reach command: ckey {ckey} for {discord_nickname}', ctx.author)
        else:
            # Игрок не найден в файле - запрашиваем ckey через модальное окно
            # Модальное окно требует respond, а не defer
            modal = CkeyInputModal(discord_nickname)
            await ctx.send_modal(modal)

            log_user_action(f'Set reach command initiated for Discord user: {discord_nickname} (not found in file)', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды set_reach: {e}")
        try:
            await ctx.followup.send(
                "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                ephemeral=True
            )
        except Exception:
            try:
                await ctx.respond(
                    "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                    ephemeral=True
                )
            except Exception:
                pass


async def remove_reach(
    ctx: discord.ApplicationContext,
    user: discord.Option(discord.Member, "Пользователь Discord (можно использовать @пользователь)", required=False, default=None)
):
    """
    Команда для удаления достижения у игрока через dropdown меню.

    Args:
        ctx: контекст команды Discord
        user: пользователь Discord (можно использовать пинг @пользователь)
    """
    try:
        # Проверка прав
        user_roles = {role.id for role in ctx.author.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await ctx.respond(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Получение Discord никнейма
        if user:
            # Если передан пинг пользователя - используем его никнейм
            discord_nickname = user.display_name or user.name
        else:
            # Если пинг не передан - используем никнейм автора команды
            discord_nickname = ctx.author.display_name or ctx.author.name

        if not discord_nickname:
            await ctx.respond("Не удалось определить Discord никнейм.", ephemeral=True)
            return

        # Пытаемся найти игрока по Discord нику в файле
        result = await store.get_player_achievements_by_discord_nickname(discord_nickname)

        if result:
            # Игрок найден в файле - используем его ckey и показываем dropdown сразу
            ckey, current_achievements = result

            await ctx.defer(ephemeral=True)

            # Проверяем ckey в БД SS14 для валидации
            ckey_from_db = await db.resolve_ckey_by_player_name(ckey)

            if not ckey_from_db:
                await ctx.followup.send(
                    f"❌ Ckey '{ckey}' игрока '{discord_nickname}' не найден в базе данных SS14. "
                    "Пожалуйста, проверьте правильность данных.",
                    ephemeral=True
                )
                return

            # Используем нормализованный ckey из БД
            ckey = ckey_from_db

            # Проверка наличия достижений
            if not current_achievements or len(current_achievements) == 0:
                await ctx.followup.send(
                    f"Игрок **{discord_nickname}** ({ckey}) не имеет достижений для удаления.",
                    ephemeral=True
                )
                return

            # Получение всех достижений из каталога
            catalog_all = catalog.get_all()

            # Вычисление достижений игрока (только имеющиеся у игрока)
            player_achievements = {
                ach_id: catalog_all[ach_id].title
                for ach_id in current_achievements
                if ach_id in catalog_all
            }

            if not player_achievements:
                await ctx.followup.send(
                    f"У игрока **{discord_nickname}** ({ckey}) не найдено достижений в каталоге.",
                    ephemeral=True
                )
                return

            # Создание view с dropdown меню
            view = RemoveAchievementSelectView(ckey, discord_nickname, player_achievements)

            await ctx.followup.send(
                f"Выберите достижение для удаления у игрока **{discord_nickname}** ({ckey}):",
                view=view,
                ephemeral=True
            )

            log_user_action(f'Remove reach command: ckey {ckey} for {discord_nickname}', ctx.author)
        else:
            # Игрок не найден в файле
            await ctx.respond(
                f"Игрок с Discord никнеймом '{discord_nickname}' не найден в системе достижений.",
                ephemeral=True
            )

    except Exception as e:
            logger.error(f"Ошибка при выполнении команды remove_reach: {e}")
            try:
                await ctx.followup.send(
                    "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                    ephemeral=True
                )
            except Exception:
                try:
                    await ctx.respond(
                        "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                        ephemeral=True
                    )
                except Exception:
                    pass


class AddReachModal(discord.ui.Modal):
    """Модальное окно для добавления достижения в каталог (reachs.txt)."""

    def __init__(self):
        """Инициализация модального окна."""
        super().__init__(title="Добавление достижения в каталог")
        
        self.ach_id_input = discord.ui.InputText(
            label="ID достижения",
            placeholder="Например: first_blood (только буквы, цифры, подчеркивания)",
            min_length=1,
            max_length=50
        )
        self.add_item(self.ach_id_input)
        
        self.ach_title_input = discord.ui.InputText(
            label="Название достижения",
            placeholder="Например: Первая кровь",
            min_length=1,
            max_length=200
        )
        self.add_item(self.ach_title_input)
        
        self.ach_description_input = discord.ui.InputText(
            label="Описание достижения",
            placeholder="Например: Убей 1 живность",
            min_length=1,
            max_length=500,
            style=discord.InputTextStyle.long
        )
        self.add_item(self.ach_description_input)

    async def callback(self, interaction: discord.Interaction):
        """
        Обработчик отправки модального окна.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Получение и нормализация значений
        ach_id = self.ach_id_input.value.strip().lower()
        title = self.ach_title_input.value.strip()
        description = self.ach_description_input.value.strip()

        # Валидация ID достижения
        if not ach_id:
            await interaction.response.send_message(
                "ID достижения не может быть пустым.",
                ephemeral=True
            )
            return

        if not ACHIEVEMENT_ID_PATTERN.match(ach_id):
            await interaction.response.send_message(
                "❌ Неверный формат ID достижения. ID должен содержать только строчные буквы, цифры и подчеркивания (например: first_blood).",
                ephemeral=True
            )
            return

        if not title:
            await interaction.response.send_message(
                "Название достижения не может быть пустым.",
                ephemeral=True
            )
            return

        if not description:
            await interaction.response.send_message(
                "Описание достижения не может быть пустым.",
                ephemeral=True
            )
            return

        # Проверка на дубликаты
        if catalog.exists(ach_id):
            await interaction.response.send_message(
                f"❌ Достижение с ID '{ach_id}' уже существует в каталоге.",
                ephemeral=True
            )
            return

        try:
            # Откладываем ответ для выполнения асинхронных операций
            await interaction.response.defer(ephemeral=True)

            catalog_path = Path(ACHIEVEMENTS_CATALOG_PATH)
            
            # Создаем директорию, если её нет
            catalog_path.parent.mkdir(parents=True, exist_ok=True)

            # Атомическая запись: пишем во временный файл, затем заменяем
            new_line = f"{ach_id}|{title}|{description}\n"
            
            # Читаем существующий файл
            existing_lines = []
            if catalog_path.exists():
                with open(catalog_path, 'r', encoding='utf-8') as f:
                    existing_lines = f.readlines()

            # Создаем временный файл и записываем данные
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=catalog_path.parent,
                delete=False,
                suffix='.tmp'
            ) as temp_file:
                temp_path = Path(temp_file.name)
                
                # Записываем существующие строки
                for line in existing_lines:
                    temp_file.write(line)
                
                # Добавляем новую строку
                temp_file.write(new_line)

            # Атомически заменяем оригинальный файл
            temp_path.replace(catalog_path)

            # Перезагружаем каталог
            catalog.load()

            await interaction.followup.send(
                f"✅ Достижение **{title}** (ID: `{ach_id}`) успешно добавлено в каталог.",
                ephemeral=True
            )

            log_user_action(
                f'Achievement added to catalog: {ach_id} - {title}',
                interaction.user
            )

        except Exception as e:
            logger.error(f"Ошибка при добавлении достижения в каталог: {e}")
            await interaction.followup.send(
                f"Произошла ошибка при добавлении достижения: {e}",
                ephemeral=True
            )


async def add_reachs(ctx: discord.ApplicationContext):
    """
    Команда для добавления достижения в каталог (reachs.txt) через модальное окно.

    Args:
        ctx: контекст команды Discord
    """
    try:
        # Проверка прав
        user_roles = {role.id for role in ctx.author.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await ctx.respond(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Открываем модальное окно
        modal = AddReachModal()
        await ctx.send_modal(modal)

        log_user_action('Add reachs command initiated', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды add_reachs: {e}")
        try:
            await ctx.respond(
                "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                ephemeral=True
            )
        except Exception:
            pass


class DeleteReachSelectView(discord.ui.View):
    """View с dropdown меню для выбора достижения для удаления из каталога."""

    def __init__(self, catalog_achievements: dict[str, str]):
        """
        Инициализация view.

        Args:
            catalog_achievements: словарь {ach_id: title} всех достижений в каталоге
        """
        super().__init__(timeout=120)  # View истекает через 120 секунд
        self.catalog_achievements = catalog_achievements

        # Создание dropdown с достижениями
        if catalog_achievements:
            select = discord.ui.Select(
                placeholder="Выберите достижение для удаления из каталога",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=title,
                        value=ach_id,
                        description=f"ID: {ach_id}"[:100]  # Discord ограничение длины описания
                    )
                    for ach_id, title in catalog_achievements.items()
                ]
            )
            select.callback = self.on_select
            self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        """
        Обработчик выбора достижения из dropdown.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        selected_ach_id = interaction.data['values'][0]

        try:
            # Откладываем ответ для выполнения асинхронных операций
            await interaction.response.defer(ephemeral=True)

            # Проверяем, существует ли достижение в каталоге
            if not catalog.exists(selected_ach_id):
                ach_title = self.catalog_achievements.get(selected_ach_id, selected_ach_id)
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Достижение '{ach_title}' не найдено в каталоге.",
                    view=None
                )
                return

            ach_title = self.catalog_achievements.get(selected_ach_id, selected_ach_id)
            catalog_path = Path(ACHIEVEMENTS_CATALOG_PATH)

            # Читаем существующий файл каталога
            if not catalog_path.exists():
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content="Файл каталога достижений не найден.",
                    view=None
                )
                return

            # Читаем все строки из файла
            with open(catalog_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Фильтруем строку с удаляемым достижением
            filtered_lines = []
            removed_from_catalog = False
            for line in lines:
                line_stripped = line.strip()
                # Игнорируем пустые строки и комментарии
                if not line_stripped or line_stripped.startswith('#'):
                    filtered_lines.append(line)
                    continue

                # Парсим строку формата: id|title|description
                parts = line_stripped.split('|')
                if len(parts) >= 1:
                    line_ach_id = parts[0].strip().lower()
                    if line_ach_id == selected_ach_id.lower():
                        # Пропускаем эту строку (удаляем)
                        removed_from_catalog = True
                        continue

                filtered_lines.append(line)

            if not removed_from_catalog:
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Достижение '{ach_title}' не найдено в файле каталога.",
                    view=None
                )
                return

            # Атомически записываем обновленный каталог
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=catalog_path.parent,
                delete=False,
                suffix='.tmp'
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.writelines(filtered_lines)

            # Атомически заменяем оригинальный файл
            temp_path.replace(catalog_path)

            # Удаляем достижение у всех игроков в players_reachs.txt
            count_removed_from_players = await store.remove_achievement_from_all_players(selected_ach_id)

            # Перезагружаем каталог
            catalog.load()

            await interaction.followup.edit_message(
                interaction.message.id,
                content=(
                    f"✅ Достижение **{ach_title}** (ID: `{selected_ach_id}`) успешно удалено из каталога.\n"
                    f"Также удалено у {count_removed_from_players} игроков."
                ),
                view=None
            )

            log_user_action(
                f'Achievement deleted from catalog: {selected_ach_id} - {ach_title} (removed from {count_removed_from_players} players)',
                interaction.user
            )

        except Exception as e:
            logger.error(f"Ошибка при удалении достижения {selected_ach_id} из каталога: {e}")
            try:
                await interaction.followup.edit_message(
                    interaction.message.id,
                    content=f"Произошла ошибка при удалении достижения: {e}",
                    view=None
                )
            except Exception:
                try:
                    await interaction.followup.send(
                        f"Произошла ошибка при удалении достижения: {e}",
                        ephemeral=True
                    )
                except Exception:
                    pass

    async def on_timeout(self):
        """Обработчик истечения времени ожидания."""
        for item in self.children:
            item.disabled = True


class EditReachSelectView(discord.ui.View):
    """View с dropdown меню для выбора достижения для редактирования."""

    def __init__(self, catalog_achievements: dict[str, tuple[str, str]]):
        """
        Инициализация view.

        Args:
            catalog_achievements: словарь {ach_id: (title, description)} всех достижений в каталоге
        """
        super().__init__(timeout=120)
        self.catalog_achievements = catalog_achievements

        # Создание dropdown с достижениями
        if catalog_achievements:
            select = discord.ui.Select(
                placeholder="Выберите достижение для редактирования",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=title,
                        value=ach_id,
                        description=description[:100] if description else f"ID: {ach_id}"
                    )
                    for ach_id, (title, description) in catalog_achievements.items()
                ]
            )
            select.callback = self.on_select
            self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        """
        Обработчик выбора достижения из dropdown.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        selected_ach_id = interaction.data['values'][0]

        # Проверяем, существует ли достижение
        if selected_ach_id not in self.catalog_achievements:
            await interaction.response.send_message(
                "Выбранное достижение не найдено в каталоге.",
                ephemeral=True
            )
            return

        title, description = self.catalog_achievements[selected_ach_id]

        # Открываем модальное окно с предзаполненными данными
        modal = EditReachModal(selected_ach_id, title, description)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        """Обработчик истечения времени ожидания."""
        for item in self.children:
            item.disabled = True


class EditReachModal(discord.ui.Modal):
    """Модальное окно для редактирования достижения в каталоге (reachs.txt)."""

    def __init__(self, ach_id: str, current_title: str, current_description: str):
        """
        Инициализация модального окна.

        Args:
            ach_id: ID достижения (нельзя редактировать)
            current_title: текущее название
            current_description: текущее описание
        """
        super().__init__(title="Редактирование достижения")
        self.ach_id = ach_id

        # ID достижения (только для отображения, редактируется, но значение игнорируется)
        self.ach_id_input = discord.ui.InputText(
            label="ID достижения (нельзя изменить)",
            placeholder=ach_id,
            value=ach_id,
            min_length=1,
            max_length=50,
            required=False
        )
        self.add_item(self.ach_id_input)

        self.ach_title_input = discord.ui.InputText(
            label="Название достижения",
            placeholder="Например: Первая кровь",
            value=current_title,
            min_length=1,
            max_length=200
        )
        self.add_item(self.ach_title_input)

        self.ach_description_input = discord.ui.InputText(
            label="Описание достижения",
            placeholder="Например: Убей 1 живность",
            value=current_description,
            min_length=1,
            max_length=500,
            style=discord.InputTextStyle.long
        )
        self.add_item(self.ach_description_input)

    async def callback(self, interaction: discord.Interaction):
        """
        Обработчик отправки модального окна.

        Args:
            interaction: взаимодействие Discord
        """
        # Проверка прав (defense-in-depth)
        user_roles = {role.id for role in interaction.user.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await interaction.response.send_message(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Получение и нормализация значений
        # ID не меняется, используем сохраненный
        title = self.ach_title_input.value.strip()
        description = self.ach_description_input.value.strip()

        # Валидация
        if not title:
            await interaction.response.send_message(
                "Название достижения не может быть пустым.",
                ephemeral=True
            )
            return

        if not description:
            await interaction.response.send_message(
                "Описание достижения не может быть пустым.",
                ephemeral=True
            )
            return

        # Проверяем, существует ли достижение
        if not catalog.exists(self.ach_id):
            await interaction.response.send_message(
                f"Достижение с ID '{self.ach_id}' не найдено в каталоге.",
                ephemeral=True
            )
            return

        try:
            # Откладываем ответ для выполнения асинхронных операций
            await interaction.response.defer(ephemeral=True)

            catalog_path = Path(ACHIEVEMENTS_CATALOG_PATH)

            if not catalog_path.exists():
                await interaction.followup.send(
                    "Файл каталога достижений не найден.",
                    ephemeral=True
                )
                return

            # Читаем все строки из файла
            with open(catalog_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Обновляем строку с редактируемым достижением
            updated_lines = []
            found = False
            for line in lines:
                line_stripped = line.strip()
                # Игнорируем пустые строки и комментарии - сохраняем как есть
                if not line_stripped or line_stripped.startswith('#'):
                    updated_lines.append(line)
                    continue

                # Парсим строку формата: id|title|description
                parts = line_stripped.split('|')
                if len(parts) >= 1:
                    line_ach_id = parts[0].strip().lower()
                    if line_ach_id == self.ach_id.lower():
                        # Заменяем эту строку новой, сохраняя оригинальное окончание строки
                        # Определяем окончание строки (может быть \n, \r\n или отсутствовать)
                        line_ending = ''
                        if line.endswith('\r\n'):
                            line_ending = '\r\n'
                        elif line.endswith('\n'):
                            line_ending = '\n'
                        elif line.endswith('\r'):
                            line_ending = '\r'
                        
                        new_line = f"{self.ach_id}|{title}|{description}{line_ending}"
                        updated_lines.append(new_line)
                        found = True
                        continue

                # Сохраняем строку без изменений
                updated_lines.append(line)

            if not found:
                await interaction.followup.send(
                    f"Достижение с ID '{self.ach_id}' не найдено в файле каталога.",
                    ephemeral=True
                )
                return

            # Атомически записываем обновленный каталог
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=catalog_path.parent,
                delete=False,
                suffix='.tmp'
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.writelines(updated_lines)

            # Атомически заменяем оригинальный файл
            temp_path.replace(catalog_path)

            # Перезагружаем каталог
            catalog.load()

            await interaction.followup.send(
                f"✅ Достижение **{title}** (ID: `{self.ach_id}`) успешно обновлено в каталоге.",
                ephemeral=True
            )

            log_user_action(
                f'Achievement edited in catalog: {self.ach_id} - {title}',
                interaction.user
            )

        except Exception as e:
            logger.error(f"Ошибка при редактировании достижения в каталоге: {e}")
            await interaction.followup.send(
                f"Произошла ошибка при редактировании достижения: {e}",
                ephemeral=True
            )


async def edit_reachs(ctx: discord.ApplicationContext):
    """
    Команда для редактирования достижения в каталоге (reachs.txt) через модальное окно.

    Args:
        ctx: контекст команды Discord
    """
    try:
        # Проверка прав
        user_roles = {role.id for role in ctx.author.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await ctx.respond(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Получение всех достижений из каталога
        catalog_all = catalog.get_all()

        if not catalog_all:
            await ctx.respond(
                "Каталог достижений пуст.",
                ephemeral=True
            )
            return

        # Создание словаря для dropdown {ach_id: (title, description)}
        catalog_achievements = {
            ach_id: (ach_def.title, ach_def.description)
            for ach_id, ach_def in catalog_all.items()
        }

        # Создание view с dropdown меню
        view = EditReachSelectView(catalog_achievements)

        await ctx.respond(
            "Выберите достижение для редактирования:",
            view=view,
            ephemeral=True
        )

        log_user_action('Edit reachs command initiated', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды edit_reachs: {e}")
        try:
            await ctx.respond(
                "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                ephemeral=True
            )
        except Exception:
            pass


async def delete_reachs(ctx: discord.ApplicationContext):
    """
    Команда для удаления достижения из каталога (reachs.txt) через dropdown меню.

    Args:
        ctx: контекст команды Discord
    """
    try:
        # Проверка прав
        user_roles = {role.id for role in ctx.author.roles}
        if not any(role_id in user_roles for role_id in ACHIEVEMENTS_ALLOWED_ROLE_IDS):
            await ctx.respond(
                "У вас нет прав на использование этой команды.",
                ephemeral=True
            )
            return

        # Получение всех достижений из каталога
        catalog_all = catalog.get_all()

        if not catalog_all:
            await ctx.respond(
                "Каталог достижений пуст.",
                ephemeral=True
            )
            return

        # Создание словаря для dropdown
        catalog_achievements = {
            ach_id: ach_def.title
            for ach_id, ach_def in catalog_all.items()
        }

        # Создание view с dropdown меню
        view = DeleteReachSelectView(catalog_achievements)

        await ctx.respond(
            "Выберите достижение для удаления из каталога:",
            view=view,
            ephemeral=True
        )

        log_user_action('Delete reachs command initiated', ctx.author)

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды delete_reachs: {e}")
        try:
            await ctx.respond(
                "Произошла ошибка при запуске команды. Пожалуйста, попробуйте позже.",
                ephemeral=True
            )
        except Exception:
            pass
