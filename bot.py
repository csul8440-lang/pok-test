"""
bot.py — Точка входа. Инициализирует бота, загружает коги и подключается к БД.
База данных: SQLite (файл data/modbot.db, создаётся автоматически).
"""

import discord
from discord.ext import commands
import asyncio
import os
import logging
from utils.database import Database, DB_PATH
from utils.config import BotConfig

# ──────────────────────────────────────────────
# Настройка логирования в файл и консоль
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("bot")

# ──────────────────────────────────────────────
# Интенты — все привилегированные включены
# ──────────────────────────────────────────────
intents = discord.Intents.all()


class ModerationBot(commands.Bot):
    """Главный класс бота с поддержкой нескольких серверов."""

    def __init__(self):
        super().__init__(
            command_prefix=self._get_prefix,   # динамический префикс на сервер
            intents=intents,
            help_command=None,                  # отключаем стандартный help
            owner_ids=BotConfig.OWNER_IDS,      # ID владельцев бота
        )
        self.db: Database = None               # будет инициализировано в setup_hook
        self.config = BotConfig()

    # ──────────────────────────────────────────
    # Динамический префикс (берётся из БД)
    # ──────────────────────────────────────────
    async def _get_prefix(self, bot, message: discord.Message):
        if not message.guild:
            return "!"
        prefix = await self.db.get_guild_prefix(message.guild.id)
        return prefix or "!"

    # ──────────────────────────────────────────
    # setup_hook вызывается до on_ready
    # ──────────────────────────────────────────
    async def setup_hook(self):
        # Подключение к SQLite (файл data/modbot.db создаётся автоматически)
        self.db = Database(DB_PATH)
        await self.db.connect()
        await self.db.init_tables()
        log.info("База данных SQLite подключена и таблицы инициализированы.")

        # Загрузка всех когов
        cogs = [
            "cogs.setup",          # /setup — первичная настройка сервера
            "cogs.moderation",     # бан, кик, мут, варн, предупреждения
            "cogs.tickets",        # система тикетов
            "cogs.logging",        # логирование событий
            "cogs.stats",          # статистика действий
            "cogs.automod",        # автомодерация (фильтры слов, спам и т.д.)
            "cogs.settings",       # настройки прямо из Discord
            "cogs.punishment",     # история наказаний и апелляции
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                log.info(f"Ког загружен: {cog}")
            except Exception as e:
                log.error(f"Ошибка загрузки кога {cog}: {e}")

        # Синхронизация slash-команд глобально
        await self.tree.sync()
        log.info("Slash-команды синхронизированы.")

    async def on_ready(self):
        log.info(f"Бот запущен: {self.user} (ID: {self.user.id})")
        log.info(f"Серверов: {len(self.guilds)}")
        # Устанавливаем статус
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} серверов | /setup"
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        """Автоматически создаём запись в БД при добавлении на сервер."""
        await self.db.create_guild_config(guild.id)
        log.info(f"Добавлен на сервер: {guild.name} (ID: {guild.id})")

    async def on_guild_remove(self, guild: discord.Guild):
        log.info(f"Удалён с сервера: {guild.name} (ID: {guild.id})")


async def main():
    bot = ModerationBot()
    # ── Вставьте ваш токен сюда ──────────────────────
    TOKEN = "ВАШ_ТОКЕН_ЗДЕСЬ"
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
