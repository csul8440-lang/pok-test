"""
cogs/punishment.py — История наказаний, апелляции, управление кейсами.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timezone
from utils.config import BotConfig
from utils.helpers import make_embed

log = logging.getLogger("punishment")


class AppealModal(discord.ui.Modal, title="Апелляция на наказание"):
    """Форма подачи апелляции."""
    reason = discord.ui.TextInput(
        label="Почему наказание несправедливо?",
        style=discord.TextStyle.paragraph,
        placeholder="Опишите подробно...",
        max_length=1000,
        required=True
    )
    evidence = discord.ui.TextInput(
        label="Доказательства (ссылки, описание)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    def __init__(self, case_id: int, guild_id: int):
        super().__init__()
        self.case_id = case_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = await interaction.client.db.get_guild_config(self.guild_id)
        if not cfg or not cfg["mod_log_channel"]:
            return await interaction.response.send_message(
                embed=make_embed("❌ Апелляции не настроены на этом сервере.", BotConfig.COLOR_ERROR),
                ephemeral=True
            )
        channel = interaction.guild.get_channel(cfg["mod_log_channel"])
        if not channel:
            return

        embed = discord.Embed(
            title=f"📩 Апелляция | Кейс #{self.case_id}",
            color=BotConfig.COLOR_WARNING,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Пользователь",   value=f"{interaction.user.mention} (`{interaction.user.id}`)")
        embed.add_field(name="Причина апелляции", value=self.reason.value, inline=False)
        if self.evidence.value:
            embed.add_field(name="Доказательства", value=self.evidence.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Кнопки для модераторов
        view = AppealReviewView(interaction.user.id, self.case_id)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(
            embed=make_embed("✅ Апелляция отправлена модераторам.", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


class AppealReviewView(discord.ui.View):
    """Кнопки для рассмотрения апелляции модераторами."""

    def __init__(self, user_id: int, case_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.case_id = case_id

    @discord.ui.button(label="✅ Принять апелляцию", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        embed = interaction.message.embeds[0]
        embed.color = BotConfig.COLOR_SUCCESS
        embed.add_field(name="✅ Решение", value=f"Принята модератором {interaction.user.mention}")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        # Уведомляем пользователя
        member = interaction.guild.get_member(self.user_id)
        if member:
            try:
                await member.send(
                    embed=make_embed(
                        f"✅ Ваша апелляция по кейсу #{self.case_id} **принята**.",
                        BotConfig.COLOR_SUCCESS
                    )
                )
            except discord.Forbidden:
                pass

    @discord.ui.button(label="❌ Отклонить апелляцию", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        embed = interaction.message.embeds[0]
        embed.color = BotConfig.COLOR_ERROR
        embed.add_field(name="❌ Решение", value=f"Отклонена модератором {interaction.user.mention}")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        member = interaction.guild.get_member(self.user_id)
        if member:
            try:
                await member.send(
                    embed=make_embed(
                        f"❌ Ваша апелляция по кейсу #{self.case_id} **отклонена**.",
                        BotConfig.COLOR_ERROR
                    )
                )
            except discord.Forbidden:
                pass


class Punishment(commands.Cog):
    """Управление кейсами наказаний и апелляции."""

    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────
    # /case — просмотр конкретного кейса
    # ──────────────────────────────────────────
    @app_commands.command(name="case", description="Просмотреть кейс наказания")
    @app_commands.describe(case_id="Номер кейса")
    @app_commands.checks.has_permissions(kick_members=True)
    async def case(self, interaction: discord.Interaction, case_id: int):
        await interaction.response.defer(ephemeral=True)
        record = await self.bot.db._fetchone(
            "SELECT * FROM mod_actions WHERE id=? AND guild_id=?",
            (case_id, interaction.guild_id)
        )
        if not record:
            return await interaction.followup.send(
                embed=make_embed(f"❌ Кейс #{case_id} не найден.", BotConfig.COLOR_ERROR)
            )
        embed = discord.Embed(
            title=f"📋 Кейс #{case_id} — {record['action'].upper()}",
            color=BotConfig.COLOR_MOD,
            timestamp=record["created_at"]
        )
        embed.add_field(name="Пользователь", value=f"<@{record['user_id']}> (`{record['user_id']}`)")
        embed.add_field(name="Модератор",    value=f"<@{record['mod_id']}> (`{record['mod_id']}`)")
        embed.add_field(name="Причина",      value=record["reason"] or "Не указана", inline=False)
        if record["duration"]:
            from utils.helpers import format_duration
            embed.add_field(name="Длительность", value=format_duration(record["duration"]))
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────
    # /appeal — подать апелляцию
    # ──────────────────────────────────────────
    @app_commands.command(name="appeal", description="Подать апелляцию на наказание")
    @app_commands.describe(case_id="Номер вашего кейса")
    async def appeal(self, interaction: discord.Interaction, case_id: int):
        # Проверяем, принадлежит ли кейс этому пользователю
        record = await self.bot.db._fetchone(
            "SELECT * FROM mod_actions WHERE id=? AND guild_id=? AND user_id=?",
            (case_id, interaction.guild_id, interaction.user.id)
        )
        if not record:
            return await interaction.response.send_message(
                embed=make_embed("❌ Кейс не найден или не принадлежит вам.", BotConfig.COLOR_ERROR),
                ephemeral=True
            )
        await interaction.response.send_modal(AppealModal(case_id, interaction.guild_id))

    # ──────────────────────────────────────────
    # /reason — изменить причину кейса
    # ──────────────────────────────────────────
    @app_commands.command(name="reason", description="Изменить причину наказания")
    @app_commands.describe(case_id="Номер кейса", new_reason="Новая причина")
    @app_commands.checks.has_permissions(kick_members=True)
    async def reason(self, interaction: discord.Interaction, case_id: int, new_reason: str):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.conn.execute(
            "UPDATE mod_actions SET reason=? WHERE id=? AND guild_id=?",
            (new_reason, case_id, interaction.guild_id)
        ) as cur:
            await self.bot.db.conn.commit()
            updated = cur.rowcount > 0
        if not updated:
            return await interaction.followup.send(
                embed=make_embed("❌ Кейс не найден.", BotConfig.COLOR_ERROR)
            )
        await interaction.followup.send(
            embed=make_embed(f"✅ Причина кейса #{case_id} обновлена.", BotConfig.COLOR_SUCCESS)
        )

    # ──────────────────────────────────────────
    # /myhistory — пользователь смотрит свои наказания
    # ──────────────────────────────────────────
    @app_commands.command(name="myhistory", description="Посмотреть свои наказания")
    async def myhistory(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        actions = await self.bot.db.get_user_history(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(
            title="📋 Мои наказания",
            color=BotConfig.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        if not actions:
            embed.description = "У вас нет наказаний. Так держать! 🌟"
        else:
            for a in actions[:10]:
                embed.add_field(
                    name=f"[{a['action'].upper()}] Кейс #{a['id']}",
                    value=f"Причина: {a['reason'] or '—'} | {discord.utils.format_dt(a['created_at'], 'R')}",
                    inline=False
                )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Punishment(bot))
