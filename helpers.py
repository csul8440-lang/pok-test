"""
utils/helpers.py — Вспомогательные функции: парсинг времени, embed'ы, проверки прав.
"""

import discord
import re
from utils.config import BotConfig


# ──────────────────────────────────────────────
# Парсинг длительности из строки
# Поддерживает: 10s, 5m, 2h, 1d, 1w
# ──────────────────────────────────────────────
DURATION_PATTERN = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)

UNIT_TO_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_duration(duration_str: str) -> int | None:
    """
    Переводит строку типа '2h30m' или '1d' в секунды.
    Возвращает None если формат неверный.
    """
    matches = DURATION_PATTERN.findall(duration_str)
    if not matches:
        return None
    total = 0
    for amount, unit in matches:
        total += int(amount) * UNIT_TO_SECONDS[unit.lower()]
    return total if total > 0 else None


def format_duration(seconds: int) -> str:
    """
    Переводит секунды в читаемую строку: '2ч 30м'.
    """
    if seconds <= 0:
        return "0с"
    parts = []
    units = [("д", 86400), ("ч", 3600), ("м", 60), ("с", 1)]
    for label, size in units:
        if seconds >= size:
            parts.append(f"{seconds // size}{label}")
            seconds %= size
    return " ".join(parts)


# ──────────────────────────────────────────────
# Создание простого embed-сообщения
# ──────────────────────────────────────────────
def make_embed(description: str, color: int = BotConfig.COLOR_INFO) -> discord.Embed:
    """Быстрое создание embed'а с описанием."""
    return discord.Embed(description=description, color=color)


# ──────────────────────────────────────────────
# Проверки прав через БД (роль модератора)
# ──────────────────────────────────────────────
async def has_mod_perms(bot, member: discord.Member) -> bool:
    """True если участник — модератор или выше."""
    if member.guild_permissions.kick_members:
        return True
    cfg = await bot.db.get_guild_config(member.guild.id)
    if cfg and cfg["mod_role"]:
        return any(r.id == cfg["mod_role"] for r in member.roles)
    return False


async def has_admin_perms(bot, member: discord.Member) -> bool:
    """True если участник — администратор."""
    if member.guild_permissions.administrator:
        return True
    cfg = await bot.db.get_guild_config(member.guild.id)
    if cfg and cfg["admin_role"]:
        return any(r.id == cfg["admin_role"] for r in member.roles)
    return False
