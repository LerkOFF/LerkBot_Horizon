"""
Cog для управления достижениями игроков SS14 через Discord команды.
"""
import discord
import logging
from database import db
from services.achievements_catalog import catalog
from services.player_achievements_store import store
from config import ACHIEVEMENTS_ALLOWED_ROLE_IDS
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
                ach_id: ach_def.title
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

    def __init__(self, ckey: str, ds_nickname: str, available_achievements: dict[str, str]):
        """
        Инициализация view.

        Args:
            ckey: ckey игрока
            ds_nickname: Discord никнейм игрока
            available_achievements: словарь {ach_id: title} доступных достижений
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
                        description=title[:100]  # Discord ограничение длины описания
                    )
                    for ach_id, title in available_achievements.items()
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
                ach_title = self.available_achievements.get(selected_ach_id, selected_ach_id)
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
                ach_title = self.available_achievements.get(selected_ach_id, selected_ach_id)
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
                ach_title = self.available_achievements.get(selected_ach_id, selected_ach_id)
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
                ach_id: ach_def.title
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
