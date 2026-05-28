"""
cogs/stats.py — Статистика действий модераторов и сервера.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timezone
from utils.config import BotConfig
from utils.helpers import make_embed

log = logging.getLogger("stats")


class Stats(commands.Cog):
    """Статистика: топ модераторов, активность, история."""

    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────
    # /modstats — статистика конкретного мода
    # ──────────────────────────────────────────
    @app_commands.command(name="modstats", description="Статистика действий модератора")
    @app_commands.describe(member="Модератор (по умолчанию — вы)")
    async def modstats(
        self, interaction: discord.Interaction,
        member: discord.Member = None
    ):
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        stats = await self.bot.db.get_mod_stats(interaction.guild_id, target.id)

        embed = discord.Embed(
            title=f"📊 Статистика — {target.display_name}",
            color=BotConfig.COLOR_MOD,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        if not stats:
            embed.description = "Нет данных о действиях."
        else:
            total = stats["bans"] + stats["kicks"] + stats["mutes"] + stats["warns"]
            embed.add_field(name=f"{BotConfig.EMOJI_BAN} Банов",        value=str(stats["bans"]))
            embed.add_field(name=f"{BotConfig.EMOJI_KICK} Киков",       value=str(stats["kicks"]))
            embed.add_field(name=f"{BotConfig.EMOJI_MUTE} Мутов",       value=str(stats["mutes"]))
            embed.add_field(name=f"{BotConfig.EMOJI_WARN} Варнов",      value=str(stats["warns"]))
            embed.add_field(name=f"{BotConfig.EMOJI_UNBAN} Разбанов",   value=str(stats["unbans"]))
            embed.add_field(name=f"{BotConfig.EMOJI_UNMUTE} Размутов",  value=str(stats["unmutes"]))
            embed.add_field(name="📈 Всего действий", value=str(total), inline=False)
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────
    # /topmod — топ модераторов по активности
    # ──────────────────────────────────────────
    @app_commands.command(name="topmod", description="Топ самых активных модераторов")
    async def topmod(self, interaction: discord.Interaction):
        await interaction.response.defer()
        stats = await self.bot.db.get_guild_mod_stats(interaction.guild_id)

        embed = discord.Embed(
            title="🏆 Топ модераторов",
            color=BotConfig.COLOR_MOD,
            timestamp=datetime.now(timezone.utc)
        )
        medals = ["🥇", "🥈", "🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        if not stats:
            embed.description = "Нет данных."
        else:
            lines = []
            for i, s in enumerate(stats):
                mod = interaction.guild.get_member(s["mod_id"])
                name = mod.display_name if mod else f"ID:{s['mod_id']}"
                medal = medals[i] if i < len(medals) else "•"
                lines.append(
                    f"{medal} **{name}** — {s['total']} действий "
                    f"({BotConfig.EMOJI_BAN}{s['bans']} "
                    f"{BotConfig.EMOJI_KICK}{s['kicks']} "
                    f"{BotConfig.EMOJI_MUTE}{s['mutes']} "
                    f"{BotConfig.EMOJI_WARN}{s['warns']})"
                )
            embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────
    # /serverstats — общая статистика сервера
    # ──────────────────────────────────────────
    @app_commands.command(name="serverstats", description="Статистика сервера")
    async def serverstats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild

        # Статистика из БД
        total_actions = await self.bot.db._fetchval(
            "SELECT COUNT(*) FROM mod_actions WHERE guild_id=?", (guild.id,)
        )
        total_bans = await self.bot.db._fetchval(
            "SELECT COUNT(*) FROM mod_actions WHERE guild_id=? AND action='ban'", (guild.id,)
        )
        total_warns = await self.bot.db._fetchval(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=?", (guild.id,)
        )
        total_tickets = await self.bot.db._fetchval(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=?", (guild.id,)
        )
        open_tickets = await self.bot.db._fetchval(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status='open'", (guild.id,)
        )

        embed = discord.Embed(
            title=f"📊 Статистика — {guild.name}",
            color=BotConfig.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        # Участники
        bots    = sum(1 for m in guild.members if m.bot)
        humans  = guild.member_count - bots
        embed.add_field(name="👥 Участников",    value=f"{guild.member_count} ({humans} людей, {bots} ботов)")
        embed.add_field(name="📅 Создан",         value=discord.utils.format_dt(guild.created_at, "D"))
        embed.add_field(name="👑 Владелец",       value=guild.owner.mention if guild.owner else "?")
        embed.add_field(name="📋 Каналов",        value=str(len(guild.channels)))
        embed.add_field(name="🎭 Ролей",          value=str(len(guild.roles)))
        embed.add_field(name="😀 Эмодзи",        value=str(len(guild.emojis)))
        embed.add_field(name="🔨 Всего модерации",value=str(total_actions))
        embed.add_field(name="🔨 Банов",          value=str(total_bans))
        embed.add_field(name="⚠️ Варнов",        value=str(total_warns))
        embed.add_field(name="🎫 Тикетов",        value=f"{total_tickets} ({open_tickets} открытых)")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Stats(bot))
