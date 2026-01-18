"""
Сервис для загрузки и кэширования каталога достижений из reachs.txt.
"""
import re
import logging
from typing import Optional
from dataclasses import dataclass
from pathlib import Path
from config import ACHIEVEMENTS_CATALOG_PATH

logger = logging.getLogger(__name__)

# Регулярное выражение для валидации ID достижения: только буквы, цифры, подчеркивания
ACHIEVEMENT_ID_PATTERN = re.compile(r'^[a-z0-9_]+$')


@dataclass
class AchDefinition:
    """Определение достижения."""
    id: str
    title: str
    description: str


class AchievementsCatalog:
    """Каталог достижений с кэшированием."""

    def __init__(self):
        self._catalog: dict[str, AchDefinition] = {}
        self._loaded = False

    def load(self) -> None:
        """
        Загрузить каталог достижений из файла.
        Игнорирует пустые строки и строки, начинающиеся с #.
        """
        catalog_path = Path(ACHIEVEMENTS_CATALOG_PATH)

        if not catalog_path.exists():
            logger.warning(f"Файл каталога достижений не найден: {catalog_path}")
            self._catalog = {}
            self._loaded = True
            return

        self._catalog = {}
        line_number = 0

        try:
            with open(catalog_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line_number += 1
                    line = line.strip()

                    # Игнорировать пустые строки и комментарии
                    if not line or line.startswith('#'):
                        continue

                    # Парсинг формата: id|title|description
                    parts = line.split('|')
                    if len(parts) != 3:
                        logger.warning(
                            f"Неверный формат в файле {catalog_path}, строка {line_number}: "
                            f"ожидается 'id|title|description', получено: {line}"
                        )
                        continue

                    ach_id = parts[0].strip().lower()
                    title = parts[1].strip()
                    description = parts[2].strip()

                    # Валидация ID достижения
                    if not ACHIEVEMENT_ID_PATTERN.match(ach_id):
                        logger.warning(
                            f"Неверный ID достижения в файле {catalog_path}, строка {line_number}: "
                            f"'{ach_id}' должен содержать только строчные буквы, цифры и подчеркивания"
                        )
                        continue

                    self._catalog[ach_id] = AchDefinition(
                        id=ach_id,
                        title=title,
                        description=description
                    )

            logger.info(f"Загружено {len(self._catalog)} достижений из {catalog_path}")
            self._loaded = True

        except Exception as e:
            logger.error(f"Ошибка при загрузке каталога достижений из {catalog_path}: {e}")
            self._catalog = {}
            self._loaded = True
            raise

    def get_all(self) -> dict[str, AchDefinition]:
        """
        Получить все достижения.

        Returns:
            Словарь {ach_id: AchDefinition}
        """
        if not self._loaded:
            self.load()
        return self._catalog.copy()

    def exists(self, ach_id: str) -> bool:
        """
        Проверить существование достижения по ID.

        Args:
            ach_id: ID достижения (будет нормализован: trim + lowercase)

        Returns:
            True если достижение существует
        """
        if not self._loaded:
            self.load()

        normalized_id = ach_id.strip().lower()
        return normalized_id in self._catalog

    def get(self, ach_id: str) -> Optional[AchDefinition]:
        """
        Получить определение достижения по ID.

        Args:
            ach_id: ID достижения (будет нормализован)

        Returns:
            AchDefinition или None если не найдено
        """
        if not self._loaded:
            self.load()

        normalized_id = ach_id.strip().lower()
        return self._catalog.get(normalized_id)


# Глобальный экземпляр каталога
catalog = AchievementsCatalog()
