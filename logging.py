"""
cogs/logging.py — Система логирования всех событий сервера.
Удаления, редактирования, входы, выходы, изменения ролей и т.д.
"""

import discord
from discord.ext import commands
import logging
from datetime import timezone, datetime
from utils.config import BotConfig

log = logging.getLogger("logging_cog")


class Logging(commands.Cog):
    """Логирует события сервера в выделенный канал."""

    def __init__(self, bot):
        self.bot = bot

    async def _get_log_channel(self, guild_id: int) -> discord.TextChannel | None:
        """Возвращает канал логов если логирование включено."""
        cfg = await self.bot.db.get_guild_config(guild_id)
        if not cfg or not cfg["logging_enabled"] or not cfg["log_channel"]:
            return None
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        return guild.get_channel(cfg["log_channel"])

    # ──────────────────────────────────────────
    # Удаление сообщения
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        ch = await self._get_log_channel(message.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="🗑️ Сообщение удалено",
            color=BotConfig.COLOR_ERROR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Автор",   value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Канал",   value=message.channel.mention)
        embed.add_field(name="Содержимое", value=message.content[:1024] or "*пусто*", inline=False)
        embed.set_thumbnail(url=message.author.display_avatar.url)
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Редактирование сообщения
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        ch = await self._get_log_channel(before.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="✏️ Сообщение изменено",
            color=BotConfig.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Автор",  value=f"{before.author.mention}")
        embed.add_field(name="Канал",  value=before.channel.mention)
        embed.add_field(name="До",     value=before.content[:512] or "*пусто*", inline=False)
        embed.add_field(name="После",  value=after.content[:512]  or "*пусто*", inline=False)
        embed.add_field(name="Ссылка", value=f"[Перейти]({after.jump_url})", inline=False)
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Участник зашёл на сервер
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        ch = await self._get_log_channel(member.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="📥 Новый участник",
            description=f"{member.mention} (`{member.id}`)",
            color=BotConfig.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Аккаунт создан", value=discord.utils.format_dt(member.created_at, "R"))
        embed.add_field(name="Участников",     value=str(member.guild.member_count))
        embed.set_thumbnail(url=member.display_avatar.url)
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Участник покинул сервер
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        ch = await self._get_log_channel(member.guild.id)
        if not ch:
            return
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        embed = discord.Embed(
            title="📤 Участник покинул сервер",
            description=f"{member.mention} (`{member.id}`)",
            color=BotConfig.COLOR_WARNING,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Роли", value=", ".join(roles) or "нет", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Изменение ролей участника
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        ch = await self._get_log_channel(before.guild.id)
        if not ch:
            return
        added   = set(after.roles)  - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        embed = discord.Embed(
            title="🔄 Роли изменены",
            description=before.mention,
            color=BotConfig.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if added:
            embed.add_field(name="➕ Добавлены",  value=", ".join(r.mention for r in added))
        if removed:
            embed.add_field(name="➖ Удалены",    value=", ".join(r.mention for r in removed))
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Бан / разбан
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        ch = await self._get_log_channel(guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="🔨 Пользователь забанен",
            description=f"{user.mention} (`{user.id}`)",
            color=BotConfig.COLOR_ERROR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        ch = await self._get_log_channel(guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="✅ Пользователь разбанен",
            description=f"{user.mention} (`{user.id}`)",
            color=BotConfig.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Создание / удаление каналов
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        ch = await self._get_log_channel(channel.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="📁 Канал создан",
            description=f"**{channel.name}** (`{channel.id}`)",
            color=BotConfig.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        ch = await self._get_log_channel(channel.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="🗑️ Канал удалён",
            description=f"**{channel.name}** (`{channel.id}`)",
            color=BotConfig.COLOR_ERROR,
            timestamp=datetime.now(timezone.utc)
        )
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Создание / удаление ролей
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        ch = await self._get_log_channel(role.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="🎭 Роль создана",
            description=f"{role.mention} (`{role.id}`)",
            color=BotConfig.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        await ch.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        ch = await self._get_log_channel(role.guild.id)
        if not ch:
            return
        embed = discord.Embed(
            title="🗑️ Роль удалена",
            description=f"**{role.name}** (`{role.id}`)",
            color=BotConfig.COLOR_ERROR,
            timestamp=datetime.now(timezone.utc)
        )
        await ch.send(embed=embed)

    # ──────────────────────────────────────────
    # Изменение голосовых каналов
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        ch = await self._get_log_channel(member.guild.id)
        if not ch:
            return
        if before.channel == after.channel:
            return

        if not before.channel and after.channel:
            # Зашёл в голосовой
            embed = discord.Embed(
                title="🔊 Вошёл в голосовой канал",
                description=f"{member.mention} → **{after.channel.name}**",
                color=BotConfig.COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc)
            )
        elif before.channel and not after.channel:
            # Вышел из голосового
            embed = discord.Embed(
                title="🔇 Вышел из голосового канала",
                description=f"{member.mention} ← **{before.channel.name}**",
                color=BotConfig.COLOR_WARNING,
                timestamp=datetime.now(timezone.utc)
            )
        else:
            # Переместился
            embed = discord.Embed(
                title="🔀 Сменил голосовой канал",
                description=f"{member.mention}: **{before.channel.name}** → **{after.channel.name}**",
                color=BotConfig.COLOR_INFO,
                timestamp=datetime.now(timezone.utc)
            )
        await ch.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Logging(bot))
