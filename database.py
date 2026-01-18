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
                SELECT p.last_seen_user_name AS user_name,
                       SUM(pt.time_spent)    AS total_time
                FROM play_time pt
                         INNER JOIN player p ON pt.player_id = p.user_id
                GROUP BY p.last_seen_user_name
                ORDER BY total_time DESC
                    LIMIT $1 \
                """

        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(query, limit)
                return rows
        except Exception as e:
            logger.error(f"Ошибка при получении топа игроков: {e}")
            raise

    async def get_top_players_by_balance(self, limit: int = 10):
        """
        Получить топ игроков по балансу банковского счета.

        Args:
            limit: количество игроков в топе (по умолчанию 10)

        Returns:
            Список кортежей (user_name, char_name, bank_balance)
        """
        if not self.pool:
            raise RuntimeError("База данных не подключена. Вызовите connect() перед использованием.")

        query = """
            WITH ranked_balances AS (
                SELECT p.last_seen_user_name AS user_name,
                       prof.char_name,
                       prof.bank_balance,
                       ROW_NUMBER() OVER (PARTITION BY p.user_id ORDER BY prof.bank_balance DESC) AS rn
                FROM profile prof
                INNER JOIN preference pref ON prof.preference_id = pref.preference_id
                INNER JOIN player p ON pref.user_id::text::uuid = p.user_id
                WHERE prof.bank_balance IS NOT NULL
            )
            SELECT user_name, char_name, bank_balance
            FROM ranked_balances
            WHERE rn = 1
            ORDER BY bank_balance DESC
            LIMIT $1
        """

        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(query, limit)
                return rows
        except Exception as e:
            logger.error(f"Ошибка при получении топа игроков по балансу: {e}")
            raise

    async def resolve_ckey_by_player_name(self, player_name: str) -> str | None:
        """
        Разрешить ckey по имени игрока из SS14 базы данных.

        Args:
            player_name: имя игрока для поиска (case-insensitive)

        Returns:
            ckey (last_seen_user_name) или None если игрок не найден
        """
        if not self.pool:
            raise RuntimeError("База данных не подключена. Вызовите connect() перед использованием.")

        query = """
            SELECT LOWER(TRIM(p.last_seen_user_name)) AS ckey
            FROM player p
            WHERE LOWER(TRIM(p.last_seen_user_name)) = LOWER(TRIM($1))
            LIMIT 1
        """

        try:
            async with self.pool.acquire() as connection:
                row = await connection.fetchrow(query, player_name)
                if row:
                    return row['ckey']
                return None
        except Exception as e:
            logger.error(f"Ошибка при разрешении ckey для игрока '{player_name}': {e}")
            return None


# Глобальный экземпляр для использования в командах
db = SS14Database()
