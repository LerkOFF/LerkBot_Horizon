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


TOKEN = _get_env('DISCORD_TOKEN')
GUILD_IDS = _get_env_list_int('GUILD_IDS')
TRACKED_ROLES = _get_env_list_int('TRACKED_ROLES')
ROLE_ID_TO_MENTION = _get_env_int('ROLE_ID_TO_MENTION')
CKEY_CHANNEL_ID = _get_env_int('CKEY_CHANNEL_ID')
INFO_CHANNEL_ID = _get_env_int('INFO_CHANNEL_ID')
SPONSORS_FILE_PATH = _get_env('SPONSORS_FILE_PATH')
LOG_FILE_PATH = _get_env('LOG_FILE_PATH')
DISPOSABLE_FILE_PATH = _get_env('DISPOSABLE_FILE_PATH')
RESPOND_CHANNEL_IDS = _get_env_list_int('RESPOND_CHANNEL_IDS')
CAN_GIVES_ROLES = _get_env_list_str('CAN_GIVES_ROLES')
ROLE_GIVER_CHANNEL = _get_env_int('ROLE_GIVER_CHANNEL')
BOOSTY_ROLE_ID = _get_env_int('BOOSTY_ROLE_ID')
