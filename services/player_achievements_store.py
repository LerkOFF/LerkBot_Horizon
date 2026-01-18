"""
Сервис для чтения/записи достижений игроков в players_reachs.txt.
Использует атомарные операции записи и блокировки для безопасной работы с файлом.
"""
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional
from config import PLAYERS_ACHIEVEMENTS_PATH

logger = logging.getLogger(__name__)

# Блокировка для безопасного доступа к файлу из разных корутин
_file_lock = asyncio.Lock()


class PlayerAchievementsStore:
    """Хранилище достижений игроков с атомарными операциями."""

    def __init__(self):
        self._file_path = Path(PLAYERS_ACHIEVEMENTS_PATH)

    def _normalize_ckey(self, ckey: str) -> str:
        """
        Нормализовать ckey: trim + lowercase.

        Args:
            ckey: исходный ckey

        Returns:
            Нормализованный ckey
        """
        return ckey.strip().lower()

    async def _read_all(self) -> dict[str, tuple[str, set[str]]]:
        """
        Прочитать все записи из файла.

        Returns:
            Словарь {ckey: (ds_nickname, achievements_set)}
        """
        async with _file_lock:
            if not self._file_path.exists():
                return {}

            players = {}
            line_number = 0

            try:
                # Используем executor для чтения файла (не блокируем event loop)
                loop = asyncio.get_event_loop()

                def read_file_content():
                    with open(str(self._file_path), 'r', encoding='utf-8') as f:
                        return f.readlines()

                lines = await loop.run_in_executor(None, read_file_content)

                # Парсинг строк вне executor
                for line in lines:
                    line_number += 1
                    line = line.strip()

                    # Игнорировать пустые строки и комментарии
                    if not line or line.startswith('#'):
                        continue

                    # Парсинг формата: ds_nickname|ckey|ach_id_1,ach_id_2,ach_id_3
                    parts = line.split('|')
                    if len(parts) < 2:
                        logger.warning(
                            f"Неверный формат в файле {self._file_path}, строка {line_number}: "
                            f"ожидается минимум 'ds_nickname|ckey|...', получено: {line}"
                        )
                        continue

                    ds_nickname = parts[0].strip()
                    ckey = self._normalize_ckey(parts[1].strip())

                    if not ckey:
                        logger.warning(
                            f"Пустой ckey в файле {self._file_path}, строка {line_number}"
                        )
                        continue

                    # Парсинг списка достижений
                    achievements_str = parts[2].strip() if len(parts) > 2 else ""
                    if achievements_str:
                        achievements_set = {ach.strip().lower() for ach in achievements_str.split(',') if ach.strip()}
                    else:
                        achievements_set = set()

                    players[ckey] = (ds_nickname, achievements_set)

                return players

            except Exception as e:
                logger.error(f"Ошибка при чтении файла {self._file_path}: {e}")
                raise

    async def _write_all(self, players: dict[str, tuple[str, set[str]]]) -> None:
        """
        Записать все записи в файл атомарно.

        Args:
            players: словарь {ckey: (ds_nickname, achievements_set)}
        """
        async with _file_lock:
            tmp_path = None
            try:
                loop = asyncio.get_event_loop()

                # Подготовить все строки для записи
                lines = []
                for ckey, (ds_nickname, achievements_set) in players.items():
                    achievements_str = ','.join(sorted(achievements_set)) if achievements_set else ""
                    line = f"{ds_nickname}|{ckey}|{achievements_str}\n"
                    lines.append(line)

                # Атомарная запись: создаем временный файл, затем заменяем оригинал
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    dir=self._file_path.parent,
                    delete=False,
                    suffix='.tmp'
                ) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                    tmp_file.writelines(lines)

                # Замена оригинального файла атомарно
                await loop.run_in_executor(None, tmp_path.replace, self._file_path)

            except Exception as e:
                logger.error(f"Ошибка при записи файла {self._file_path}: {e}")
                # Удаляем временный файл при ошибке
                if tmp_path:
                    try:
                        await loop.run_in_executor(None, tmp_path.unlink)
                    except Exception:
                        pass
                raise

    async def get_player_achievements(self, ckey: str) -> Optional[set[str]]:
        """
        Получить достижения игрока по ckey.

        Args:
            ckey: ckey игрока

        Returns:
            set[str] с ID достижений или None если игрок не найден
        """
        normalized_ckey = self._normalize_ckey(ckey)
        players = await self._read_all()

        if normalized_ckey not in players:
            return None

        _, achievements_set = players[normalized_ckey]
        return achievements_set.copy()

    async def get_player_achievements_by_discord_nickname(
        self,
        discord_nickname: str
    ) -> Optional[tuple[str, set[str]]]:
        """
        Получить достижения игрока по Discord никнейму.

        Args:
            discord_nickname: Discord никнейм игрока

        Returns:
            tuple(ckey, achievements_set) или None если игрок не найден
        """
        discord_nickname_normalized = discord_nickname.strip()
        players = await self._read_all()

        # Поиск по Discord никнейму (первое поле в файле)
        for ckey, (ds_nickname, achievements_set) in players.items():
            if ds_nickname.strip() == discord_nickname_normalized:
                return (ckey, achievements_set.copy())

        return None

    async def upsert_player(
        self,
        ckey: str,
        ds_nickname: str,
        achievements_set: set[str]
    ) -> None:
        """
        Создать или обновить запись игрока.

        Args:
            ckey: ckey игрока
            ds_nickname: Discord никнейм (для человеческой читаемости)
            achievements_set: множество ID достижений
        """
        normalized_ckey = self._normalize_ckey(ckey)
        players = await self._read_all()

        # Нормализовать ID достижений
        normalized_achievements = {ach.strip().lower() for ach in achievements_set if ach.strip()}

        players[normalized_ckey] = (ds_nickname, normalized_achievements)
        await self._write_all(players)

        logger.info(f"Обновлена запись игрока: {ds_nickname} ({normalized_ckey}) с {len(normalized_achievements)} достижениями")

    async def add_achievement(
        self,
        ckey: str,
        ds_nickname: str,
        ach_id: str
    ) -> bool:
        """
        Добавить достижение игроку.

        Args:
            ckey: ckey игрока
            ds_nickname: Discord никнейм
            ach_id: ID достижения для добавления

        Returns:
            True если достижение было добавлено, False если уже было у игрока
        """
        normalized_ckey = self._normalize_ckey(ckey)
        normalized_ach_id = ach_id.strip().lower()

        players = await self._read_all()

        # Получить текущие достижения или создать новую запись
        if normalized_ckey in players:
            current_ds_nickname, current_achievements = players[normalized_ckey]
            # Обновляем ds_nickname если предоставлен новый (может измениться)
            ds_nickname = ds_nickname if ds_nickname else current_ds_nickname
        else:
            current_achievements = set()

        # Проверка: уже есть достижение?
        if normalized_ach_id in current_achievements:
            return False

        # Добавить достижение
        current_achievements.add(normalized_ach_id)
        players[normalized_ckey] = (ds_nickname, current_achievements)
        await self._write_all(players)

        logger.info(f"Добавлено достижение '{normalized_ach_id}' игроку {ds_nickname} ({normalized_ckey})")
        return True

    async def remove_achievement(
        self,
        ckey: str,
        ds_nickname: str,
        ach_id: str
    ) -> bool:
        """
        Удалить достижение у игрока.

        Args:
            ckey: ckey игрока
            ds_nickname: Discord никнейм
            ach_id: ID достижения для удаления

        Returns:
            True если достижение было удалено, False если его не было у игрока
        """
        normalized_ckey = self._normalize_ckey(ckey)
        normalized_ach_id = ach_id.strip().lower()

        players = await self._read_all()

        # Проверка: игрок существует?
        if normalized_ckey not in players:
            return False

        current_ds_nickname, current_achievements = players[normalized_ckey]

        # Проверка: есть ли достижение?
        if normalized_ach_id not in current_achievements:
            return False

        # Удалить достижение
        current_achievements.remove(normalized_ach_id)
        players[normalized_ckey] = (ds_nickname, current_achievements)
        await self._write_all(players)

        logger.info(f"Удалено достижение '{normalized_ach_id}' у игрока {ds_nickname} ({normalized_ckey})")
        return True

    async def remove_achievement_from_all_players(self, ach_id: str) -> int:
        """
        Удалить достижение у всех игроков.

        Args:
            ach_id: ID достижения для удаления

        Returns:
            Количество игроков, у которых было удалено достижение
        """
        normalized_ach_id = ach_id.strip().lower()
        players = await self._read_all()

        count_removed = 0

        # Удалить достижение у всех игроков
        for ckey, (ds_nickname, achievements_set) in players.items():
            if normalized_ach_id in achievements_set:
                achievements_set.remove(normalized_ach_id)
                players[ckey] = (ds_nickname, achievements_set)
                count_removed += 1

        if count_removed > 0:
            await self._write_all(players)
            logger.info(f"Удалено достижение '{normalized_ach_id}' у {count_removed} игроков")

        return count_removed


# Глобальный экземпляр хранилища
store = PlayerAchievementsStore()
