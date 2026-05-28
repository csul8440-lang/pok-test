"""
cogs/automod.py — Автоматическая модерация.
Антиспам, фильтр ссылок, капс-фильтр, фильтр слов, лимит упоминаний.
"""

import discord
from discord.ext import commands
import re
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from utils.config import BotConfig
from utils.helpers import make_embed, format_duration

log = logging.getLogger("automod")

# Регулярки
URL_PATTERN = re.compile(
    r"(https?://|discord\.gg/|discord\.com/invite/)[^\s]+",
    re.IGNORECASE
)


class Automod(commands.Cog):
    """Автоматическая модерация на основе настроек сервера."""

    def __init__(self, bot):
        self.bot = bot
        # Словарь для отслеживания спама: guild_id → {user_id → deque timestamps}
        self._spam_tracker: dict[int, dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Главный обработчик — проверяет каждое сообщение."""
        if not message.guild:
            return
        if message.author.bot:
            return
        # Пропускаем администраторов
        if message.author.guild_permissions.administrator:
            return

        cfg = await self.bot.db.get_guild_config(message.guild.id)
        if not cfg or not cfg["automod_enabled"]:
            return

        # Проверяем, не игнорируется ли канал
        is_ignored = await self.bot.db.is_channel_ignored(message.guild.id, message.channel.id)
        if is_ignored:
            return

        # ── Проверки по порядку (возвращаем при первом срабатывании) ──

        if cfg["automod_spam_enabled"]:
            if await self._check_spam(message, cfg):
                return

        if cfg["automod_words_enabled"]:
            if await self._check_banned_words(message):
                return

        if cfg["automod_links_enabled"]:
            if await self._check_links(message, cfg):
                return

        if cfg["automod_caps_enabled"]:
            if await self._check_caps(message, cfg):
                return

        if cfg["automod_mentions_enabled"]:
            if await self._check_mentions(message, cfg):
                return

    # ──────────────────────────────────────────
    # Антиспам: N сообщений за 5 секунд
    # ──────────────────────────────────────────
    async def _check_spam(self, message: discord.Message, cfg) -> bool:
        limit = cfg["automod_spam_limit"] or 5
        now = datetime.now(timezone.utc)
        window = 5  # секунд

        queue = self._spam_tracker[message.guild.id][message.author.id]
        queue.append(now)

        # Удаляем старые записи за пределами окна
        while queue and (now - queue[0]).total_seconds() > window:
            queue.popleft()

        if len(queue) >= limit:
            queue.clear()
            await message.delete()
            # Мут на 5 минут за спам
            expires = now + timedelta(minutes=5)
            try:
                await message.author.timeout(expires, reason="[Автомод] Спам")
            except discord.Forbidden:
                pass
            await self._automod_warn(
                message, "🚫 Спам",
                f"{message.author.mention}, не спамьте! Вы замучены на 5 минут."
            )
            await self.bot.db.add_mod_action(
                message.guild.id, message.author.id,
                self.bot.user.id, "mute",
                "Автомод: спам", duration=300, expires_at=expires
            )
            return True
        return False

    # ──────────────────────────────────────────
    # Фильтр запрещённых слов
    # ──────────────────────────────────────────
    async def _check_banned_words(self, message: discord.Message) -> bool:
        words = await self.bot.db.get_banned_words(message.guild.id)
        content_lower = message.content.lower()
        for word in words:
            if word in content_lower:
                await message.delete()
                await self._automod_warn(
                    message, "🤬 Запрещённое слово",
                    f"{message.author.mention}, это слово запрещено на сервере."
                )
                await self.bot.db.add_mod_action(
                    message.guild.id, message.author.id,
                    self.bot.user.id, "warn",
                    f"Автомод: запрещённое слово «{word}»"
                )
                return True
        return False

    # ──────────────────────────────────────────
    # Фильтр ссылок (с белым списком)
    # ──────────────────────────────────────────
    async def _check_links(self, message: discord.Message, cfg) -> bool:
        if not URL_PATTERN.search(message.content):
            return False

        # Получаем белый список доменов
        allowed_rows = await self.bot.db._fetchall(
            "SELECT domain FROM allowed_links WHERE guild_id = ?", (message.guild.id,)
        )
        allowed_domains = {r["domain"] for r in allowed_rows}

        # Проверяем каждую ссылку
        for url in URL_PATTERN.findall(message.content):
            url_domain = url.split("/")[2] if "://" in url else url.split("/")[0]
            if not any(url_domain.endswith(d) for d in allowed_domains):
                await message.delete()
                await self._automod_warn(
                    message, "🔗 Запрещённая ссылка",
                    f"{message.author.mention}, отправка ссылок запрещена на этом сервере."
                )
                return True
        return False

    # ──────────────────────────────────────────
    # Капс-фильтр
    # ──────────────────────────────────────────
    async def _check_caps(self, message: discord.Message, cfg) -> bool:
        content = message.content
        # Проверяем только достаточно длинные сообщения
        if len(content) < 8:
            return False
        letters = [c for c in content if c.isalpha()]
        if not letters:
            return False
        caps_percent = sum(1 for c in letters if c.isupper()) / len(letters) * 100
        threshold = cfg["automod_caps_percent"] or 70

        if caps_percent >= threshold:
            await message.delete()
            await self._automod_warn(
                message, "🔠 Слишком много заглавных",
                f"{message.author.mention}, не используйте много заглавных букв."
            )
            return True
        return False

    # ──────────────────────────────────────────
    # Лимит упоминаний
    # ──────────────────────────────────────────
    async def _check_mentions(self, message: discord.Message, cfg) -> bool:
        limit = cfg["automod_mention_limit"] or 5
        if len(message.mentions) >= limit:
            await message.delete()
            expires = datetime.now(timezone.utc) + timedelta(minutes=10)
            try:
                await message.author.timeout(expires, reason="[Автомод] Массовые упоминания")
            except discord.Forbidden:
                pass
            await self._automod_warn(
                message, "📢 Массовые упоминания",
                f"{message.author.mention}, нельзя упоминать столько людей. Мут на 10 минут."
            )
            await self.bot.db.add_mod_action(
                message.guild.id, message.author.id,
                self.bot.user.id, "mute",
                "Автомод: массовые упоминания", duration=600, expires_at=expires
            )
            return True
        return False

    # ──────────────────────────────────────────
    # Отправка предупреждения автомода в канал
    # ──────────────────────────────────────────
    async def _automod_warn(self, message: discord.Message, title: str, text: str):
        embed = discord.Embed(
            title=f"🤖 Автомодерация | {title}",
            description=text,
            color=BotConfig.COLOR_WARNING
        )
        embed.set_footer(text="Это автоматическое действие.")
        try:
            warn_msg = await message.channel.send(embed=embed, delete_after=8)
        except discord.Forbidden:
            pass
        log.info(f"Автомод сработал [{title}] на {message.author} в {message.guild}")


async def setup(bot):
    await bot.add_cog(Automod(bot))
