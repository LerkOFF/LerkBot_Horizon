import asyncpg
from config import SS14_DB_HOST, SS14_DB_PORT, SS14_DB_NAME, SS14_DB_USER, SS14_DB_PASSWORD
import logging

logger = logging.getLogger(__name__)


class SS14Database:
    """Класс для работы с базой данных SS14 (PostgreSQL)."""

    def __init__(self):
        self.pool = None

    async def connect(self):
        """Создание пула соединений с базой данных SS14."""
        try:
            self.pool = await asyncpg.create_pool(
                host=SS14_DB_HOST,
                port=SS14_DB_PORT,
                database=SS14_DB_NAME,
                user=SS14_DB_USER,
                password=SS14_DB_PASSWORD,
                min_size=2,
                max_size=10,
                timeout=10
            )
            logger.info(f"Подключение к БД SS14 ({SS14_DB_NAME}) успешно установлено")
        except Exception as e:
            logger.error(f"Ошибка подключения к БД SS14: {e}")
            raise

    async def disconnect(self):
        """Закрытие пула соединений с базой данных."""
        if self.pool:
            await self.pool.close()
            logger.info("Соединение с БД SS14 закрыто")

    async def get_top_players_by_playtime(self, limit: int = 10):
        """
        Получить топ игроков по наигранному времени.

        Args:
            limit: количество игроков в топе (по умолчанию 10)

        Returns:
            Список кортежей (player_name, total_time_spent)
        """
        if not self.pool:
            raise RuntimeError("База данных не подключена. Вызовите connect() перед использованием.")

        query = """
            SELECT p.user_name, SUM(pt.time_spent) as total_time
            FROM play_time pt
            INNER JOIN player p ON pt.player_id = p.user_id
            GROUP BY p.user_id, p.user_name
            ORDER BY total_time DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(query, limit)
                return rows
        except Exception as e:
            logger.error(f"Ошибка при получении топа игроков: {e}")
            raise


# Глобальный экземпляр для использования в командах
db = SS14Database()
