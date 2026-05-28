"""
cogs/setup.py — Мастер первичной настройки сервера.
Запускается командой /setup и проводит администратора через все шаги.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from utils.config import BotConfig
from utils.helpers import make_embed

log = logging.getLogger("setup")


class SetupWizardView(discord.ui.View):
    """Интерактивный мастер настройки с кнопками выбора."""

    def __init__(self, cog, guild: discord.Guild, user: discord.Member):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.user = user
        self.config = {}  # накапливаем настройки

    # ── Шаг 1: Как создать каналы? ──
    @discord.ui.button(label="🏗️ Бот создаст каналы", style=discord.ButtonStyle.success, row=0)
    async def auto_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("❌ Это не ваш мастер настройки.", ephemeral=True)
        await interaction.response.defer()
        # Создаём каналы автоматически
        settings_cog = self.cog.bot.cogs.get("Settings")
        if settings_cog:
            created = await settings_cog._auto_create_channels(self.guild)
            await interaction.followup.send(
                embed=make_embed(f"✅ Каналы созданы: {', '.join(created)}", BotConfig.COLOR_SUCCESS),
                ephemeral=True
            )
        await self._step_roles(interaction)

    @discord.ui.button(label="📋 Выбрать существующие каналы", style=discord.ButtonStyle.primary, row=0)
    async def manual_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("❌ Это не ваш мастер настройки.", ephemeral=True)
        # Открываем настройки каналов
        from cogs.settings import ChannelsSettingsView, Settings
        settings_cog = self.cog.bot.cogs.get("Settings")
        if settings_cog:
            await interaction.response.edit_message(
                embed=await settings_cog._channels_embed(self.guild),
                view=ChannelsSettingsView(settings_cog, self.guild)
            )

    @discord.ui.button(label="⏭️ Пропустить", style=discord.ButtonStyle.secondary, row=0)
    async def skip_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("❌ Это не ваш мастер настройки.", ephemeral=True)
        await self._step_roles(interaction)

    async def _step_roles(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="👥 Шаг 2: Роли",
            description="Как настроить роли модератора и администратора?",
            color=BotConfig.COLOR_INFO
        )
        await interaction.edit_original_response(embed=embed, view=SetupRolesView(self.cog, self.guild, self.user))


class SetupRolesView(discord.ui.View):
    def __init__(self, cog, guild, user):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.user = user

    @discord.ui.button(label="🏗️ Бот создаст роли", style=discord.ButtonStyle.success)
    async def auto_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.defer()
        settings_cog = self.cog.bot.cogs.get("Settings")
        if settings_cog:
            created = await settings_cog._auto_create_roles(self.guild)
            await interaction.followup.send(
                embed=make_embed(f"✅ Роли созданы: {', '.join(created)}", BotConfig.COLOR_SUCCESS),
                ephemeral=True
            )
        await self._finish(interaction)

    @discord.ui.button(label="👥 Выбрать существующие роли", style=discord.ButtonStyle.primary)
    async def manual_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("❌", ephemeral=True)
        from cogs.settings import RolesSettingsView
        settings_cog = self.cog.bot.cogs.get("Settings")
        if settings_cog:
            await interaction.response.edit_message(
                embed=await settings_cog._roles_embed(self.guild),
                view=RolesSettingsView(settings_cog, self.guild)
            )

    @discord.ui.button(label="⏭️ Пропустить", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            return
        await self._finish(interaction)

    async def _finish(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✅ Настройка завершена!",
            description=(
                "Бот готов к работе.\n\n"
                "**Доступные команды:**\n"
                "`/settings` — управление всеми настройками\n"
                "`/ban /kick /mute /warn` — модерация\n"
                "`/ticket-setup` — разместить панель тикетов\n"
                "`/serverstats` — статистика сервера\n"
                "`/topmod` — топ модераторов\n\n"
                "Используйте `/settings` для дальнейшей тонкой настройки."
            ),
            color=BotConfig.COLOR_SUCCESS
        )
        await interaction.edit_original_response(embed=embed, view=None)


class Setup(commands.Cog):
    """Команда первичной настройки бота на сервере."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Первичная настройка бота на сервере")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        # Создаём конфиг сервера если нет
        await self.bot.db.create_guild_config(interaction.guild_id)

        embed = discord.Embed(
            title="🚀 Мастер настройки",
            description=(
                f"Добро пожаловать, {interaction.user.mention}!\n\n"
                "Этот мастер поможет настроить бота на вашем сервере.\n\n"
                "**Шаг 1: Каналы**\n"
                "Нужно создать каналы для логов и действий модерации.\n"
                "Бот может создать их автоматически или вы можете выбрать существующие."
            ),
            color=BotConfig.COLOR_INFO
        )
        await interaction.response.send_message(
            embed=embed,
            view=SetupWizardView(self, interaction.guild, interaction.user),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Setup(bot))
