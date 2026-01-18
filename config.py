import os
import sys
from dotenv import load_dotenv

load_dotenv()

def _get_env(key: str, required: bool = True) -> str:
    """Безопасное получение переменной окружения с проверкой."""
    value = os.getenv(key)
    if required and not value:
        print(f"ОШИБКА: Отсутствует обязательная переменная окружения: {key}")
        sys.exit(1)
    return value


def _get_env_int(key: str) -> int:
    """Получение целочисленной переменной окружения."""
    value = _get_env(key)
    try:
        return int(value)
    except ValueError:
        print(f"ОШИБКА: Переменная {key} должна быть целым числом, получено: {value}")
        sys.exit(1)


def _get_env_list_int(key: str) -> list[int]:
    """Получение списка целых чисел из переменной окружения."""
    value = _get_env(key)
    try:
        return list(map(int, value.split(',')))
    except ValueError:
        print(f"ОШИБКА: Переменная {key} должна содержать числа через запятую, получено: {value}")
        sys.exit(1)


def _get_env_list_str(key: str) -> list[str]:
    """Получение списка строк из переменной окружения."""
    value = _get_env(key)
    return value.split(',')


def _get_env_optional(key: str, default: str = "") -> str:
    """Получение опциональной переменной окружения с значением по умолчанию."""
    return os.getenv(key, default)


# Discord Configuration
TOKEN = _get_env('DISCORD_TOKEN')
GUILD_IDS = _get_env_list_int('GUILD_IDS')
TRACKED_ROLES = _get_env_list_int('TRACKED_ROLES')
CKEY_CHANNEL_ID = _get_env_int('CKEY_CHANNEL_ID')
INFO_CHANNEL_ID = _get_env_int('INFO_CHANNEL_ID')
SPONSORS_FILE_PATH = _get_env('SPONSORS_FILE_PATH')
LOG_FILE_PATH = _get_env('LOG_FILE_PATH')
DISPOSABLE_FILE_PATH = _get_env('DISPOSABLE_FILE_PATH')
CAN_GIVES_ROLES = _get_env_list_str('CAN_GIVES_ROLES')
BOOSTY_ROLE_ID = _get_env_int('BOOSTY_ROLE_ID')
TOP_COMMANDS_ALLOWED_CHANNELS = _get_env_list_int('TOP_COMMANDS_ALLOWED_CHANNELS')

# SS14 Database Configuration (PostgreSQL)
SS14_DB_HOST = _get_env('DB_HOST')
SS14_DB_PORT = _get_env_int('DB_PORT')
SS14_DB_NAME = _get_env('DB_NAME')
SS14_DB_USER = _get_env('DB_USER')
SS14_DB_PASSWORD = _get_env('DB_PASSWORD')

# Achievements Configuration
ACHIEVEMENTS_CATALOG_PATH = _get_env_optional('ACHIEVEMENTS_CATALOG_PATH', 'data/reachs.txt')
PLAYERS_ACHIEVEMENTS_PATH = _get_env_optional('PLAYERS_ACHIEVEMENTS_PATH', 'data/players_reachs.txt')
ACHIEVEMENTS_ALLOWED_ROLE_IDS = _get_env_list_int('ACHIEVEMENTS_ALLOWED_ROLE_IDS')
