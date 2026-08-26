"""Atomic read/write for discord_sponsors.txt. Shared by Boosty events and site sync."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime

from config import SPONSORS_FILE_PATH

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
DEFAULT_COLOR = "#FF0000"


def _read() -> list[str]:
    try:
        with open(SPONSORS_FILE_PATH, "r", encoding="utf-8") as handle:
            return handle.readlines()
    except FileNotFoundError:
        return []


def _atomic_write(lines: list[str]) -> None:
    directory = os.path.dirname(SPONSORS_FILE_PATH) or "."
    temp_fd, temp_path = tempfile.mkstemp(dir=directory, text=True)
    try:
        os.fchmod(temp_fd, 0o664)
        with os.fdopen(temp_fd, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        os.replace(temp_path, SPONSORS_FILE_PATH)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


async def read_lines() -> list[str]:
    async with _lock:
        return _read()


async def write_lines(lines: list[str]) -> None:
    async with _lock:
        _atomic_write(lines)


async def upsert_sponsor(username: str, ckey: str, role_id: str | int, color: str | None = None) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hex_color = color if color else DEFAULT_COLOR
    record = f"{username}, {ckey}, {role_id}, {stamp}, {hex_color}\n"
    async with _lock:
        lines = _read()
        updated = False
        next_lines: list[str] = []
        for line in lines:
            if line.startswith(f"{username},"):
                next_lines.append(record)
                updated = True
            else:
                next_lines.append(line)
        if not updated:
            next_lines.append(record)
        _atomic_write(next_lines)
    logger.info("Запись спонсора %s обновлена в файле", username)


async def remove_sponsor(username: str) -> None:
    async with _lock:
        lines = _read()
        filtered = [line for line in lines if not line.startswith(f"{username},")]
        if len(filtered) == len(lines):
            return
        _atomic_write(filtered)
    logger.info("Пользователь %s удалён из файла спонсоров", username)


async def update_color(username: str, color: str) -> bool:
    async with _lock:
        lines = _read()
        found = False
        next_lines: list[str] = []
        for line in lines:
            if line.startswith(f"{username},"):
                found = True
                parts = line.strip().split(", ")
                if len(parts) >= 5:
                    parts[4] = color
                else:
                    parts.append(color)
                next_lines.append(", ".join(parts) + "\n")
            else:
                next_lines.append(line)
        if not found:
            return False
        _atomic_write(next_lines)
        return True
