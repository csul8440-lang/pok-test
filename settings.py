"""
cogs/settings.py — Настройка всего бота прямо в Discord.
Интерактивные меню, кнопки, селекторы ролей и каналов.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from utils.config import BotConfig
from utils.helpers import make_embed

log = logging.getLogger("settings")


# ──────────────────────────────────────────────
# Главная панель настроек
# ──────────────────────────────────────────────
class SettingsMainView(discord.ui.View):
    """Главное меню настроек с кнопками-разделами."""

    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="⚙️ Каналы", style=discord.ButtonStyle.primary, row=0)
    async def channels_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._channels_embed(interaction.guild),
            view=ChannelsSettingsView(self.cog, interaction.guild)
        )

    @discord.ui.button(label="👥 Роли", style=discord.ButtonStyle.primary, row=0)
    async def roles_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._roles_embed(interaction.guild),
            view=RolesSettingsView(self.cog, interaction.guild)
        )

    @discord.ui.button(label="🛡️ Модерация", style=discord.ButtonStyle.secondary, row=0)
    async def mod_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._mod_embed(interaction.guild),
            view=ModerationSettingsView(self.cog, interaction.guild)
        )

    @discord.ui.button(label="🤖 Автомод", style=discord.ButtonStyle.secondary, row=0)
    async def automod_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._automod_embed(interaction.guild),
            view=AutomodSettingsView(self.cog, interaction.guild)
        )

    @discord.ui.button(label="🎫 Тикеты", style=discord.ButtonStyle.success, row=1)
    async def tickets_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._tickets_embed(interaction.guild),
            view=TicketsSettingsView(self.cog, interaction.guild)
        )

    @discord.ui.button(label="⚠️ Варн-система", style=discord.ButtonStyle.success, row=1)
    async def warns_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._warns_embed(interaction.guild),
            view=WarnActionsView(self.cog, interaction.guild)
        )

    @discord.ui.button(label="🔤 Префикс", style=discord.ButtonStyle.secondary, row=1)
    async def prefix_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PrefixModal(self.cog))


# ──────────────────────────────────────────────
# Настройка каналов
# ──────────────────────────────────────────────
class ChannelsSettingsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        # Добавляем селекторы каналов
        self.add_item(ChannelSelect("log_channel", "📋 Канал логов", guild))
        self.add_item(ChannelSelect("mod_log_channel", "🛡️ Канал мод-логов", guild))
        self.add_item(ChannelSelect("ticket_channel", "🎫 Канал тикетов", guild))

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._main_embed(interaction.guild),
            view=SettingsMainView(self.cog, interaction.guild.id)
        )

    @discord.ui.button(label="🏗️ Создать каналы", style=discord.ButtonStyle.success, row=4)
    async def create_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Бот сам создаёт необходимые каналы."""
        await interaction.response.defer()
        created = await self.cog._auto_create_channels(interaction.guild)
        await interaction.followup.send(
            embed=make_embed(f"✅ Созданы каналы: {', '.join(created)}", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


class ChannelSelect(discord.ui.ChannelSelect):
    """Универсальный селектор канала с сохранением в БД."""

    def __init__(self, db_field: str, placeholder: str, guild: discord.Guild):
        super().__init__(
            placeholder=placeholder,
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1
        )
        self.db_field = db_field

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await interaction.client.db.update_guild_config(
            interaction.guild_id, **{self.db_field: channel.id}
        )
        await interaction.response.send_message(
            embed=make_embed(f"✅ {self.placeholder} → {channel.mention}", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


# ──────────────────────────────────────────────
# Настройка ролей
# ──────────────────────────────────────────────
class RolesSettingsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(RoleSelect("mod_role",      "🛡️ Роль модератора"))
        self.add_item(RoleSelect("admin_role",    "👑 Роль администратора"))
        self.add_item(RoleSelect("ticket_support","🎫 Роль поддержки тикетов"))

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._main_embed(interaction.guild),
            view=SettingsMainView(self.cog, interaction.guild.id)
        )

    @discord.ui.button(label="🏗️ Создать роли", style=discord.ButtonStyle.success, row=4)
    async def create_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        created = await self.cog._auto_create_roles(interaction.guild)
        await interaction.followup.send(
            embed=make_embed(f"✅ Созданы роли: {', '.join(created)}", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


class RoleSelect(discord.ui.RoleSelect):
    def __init__(self, db_field: str, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.db_field = db_field

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await interaction.client.db.update_guild_config(
            interaction.guild_id, **{self.db_field: role.id}
        )
        await interaction.response.send_message(
            embed=make_embed(f"✅ {self.placeholder} → {role.mention}", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


# ──────────────────────────────────────────────
# Настройки модерации (вкл/выкл системы)
# ──────────────────────────────────────────────
class ModerationSettingsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild

    @discord.ui.button(label="🛡️ Модерация: вкл/выкл", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_mod(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await interaction.client.db.get_guild_config(interaction.guild_id)
        new_val = not cfg["mod_enabled"] if cfg else True
        await interaction.client.db.update_guild_config(interaction.guild_id, mod_enabled=new_val)
        status = "включена ✅" if new_val else "отключена ❌"
        await interaction.response.send_message(
            embed=make_embed(f"🛡️ Модерация {status}", BotConfig.COLOR_SUCCESS if new_val else BotConfig.COLOR_ERROR),
            ephemeral=True
        )

    @discord.ui.button(label="📋 Логи: вкл/выкл", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await interaction.client.db.get_guild_config(interaction.guild_id)
        new_val = not cfg["logging_enabled"] if cfg else True
        await interaction.client.db.update_guild_config(interaction.guild_id, logging_enabled=new_val)
        status = "включены ✅" if new_val else "отключены ❌"
        await interaction.response.send_message(
            embed=make_embed(f"📋 Логи {status}", BotConfig.COLOR_SUCCESS if new_val else BotConfig.COLOR_ERROR),
            ephemeral=True
        )

    @discord.ui.button(label="🎫 Тикеты: вкл/выкл", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await interaction.client.db.get_guild_config(interaction.guild_id)
        new_val = not cfg["tickets_enabled"] if cfg else True
        await interaction.client.db.update_guild_config(interaction.guild_id, tickets_enabled=new_val)
        status = "включены ✅" if new_val else "отключены ❌"
        await interaction.response.send_message(
            embed=make_embed(f"🎫 Тикеты {status}", BotConfig.COLOR_SUCCESS if new_val else BotConfig.COLOR_ERROR),
            ephemeral=True
        )

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._main_embed(interaction.guild),
            view=SettingsMainView(self.cog, interaction.guild.id)
        )


# ──────────────────────────────────────────────
# Настройки автомодерации
# ──────────────────────────────────────────────
class AutomodSettingsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="🤖 Автомод: вкл/выкл", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await interaction.client.db.get_guild_config(interaction.guild_id)
        new_val = not cfg["automod_enabled"] if cfg else True
        await interaction.client.db.update_guild_config(interaction.guild_id, automod_enabled=new_val)
        status = "включён ✅" if new_val else "отключён ❌"
        await interaction.response.send_message(
            embed=make_embed(f"🤖 Автомод {status}", BotConfig.COLOR_SUCCESS if new_val else BotConfig.COLOR_ERROR),
            ephemeral=True
        )

    @discord.ui.button(label="🚫 Антиспам", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_spam(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await interaction.client.db.get_guild_config(interaction.guild_id)
        new_val = not cfg["automod_spam_enabled"] if cfg else True
        await interaction.client.db.update_guild_config(interaction.guild_id, automod_spam_enabled=new_val)
        await interaction.response.send_message(
            embed=make_embed(f"Антиспам {'✅' if new_val else '❌'}", BotConfig.COLOR_INFO),
            ephemeral=True
        )

    @discord.ui.button(label="🔗 Антиссылки", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await interaction.client.db.get_guild_config(interaction.guild_id)
        new_val = not cfg["automod_links_enabled"] if cfg else True
        await interaction.client.db.update_guild_config(interaction.guild_id, automod_links_enabled=new_val)
        await interaction.response.send_message(
            embed=make_embed(f"Фильтр ссылок {'✅' if new_val else '❌'}", BotConfig.COLOR_INFO),
            ephemeral=True
        )

    @discord.ui.button(label="📝 Запрещённые слова", style=discord.ButtonStyle.danger, row=1)
    async def manage_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BannedWordModal())

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._main_embed(interaction.guild),
            view=SettingsMainView(self.cog, interaction.guild.id)
        )


# ──────────────────────────────────────────────
# Настройки системы варнов
# ──────────────────────────────────────────────
class WarnActionsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="✏️ Изменить действия", style=discord.ButtonStyle.primary, row=0)
    async def edit_actions(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarnActionsModal())

    @discord.ui.button(label="↺ Сбросить к стандартным", style=discord.ButtonStyle.secondary, row=0)
    async def reset_actions(self, interaction: discord.Interaction, button: discord.ui.Button):
        default = '{"3": "mute_1h", "5": "mute_24h", "7": "kick", "10": "ban"}'
        await interaction.client.db.update_guild_config(
            interaction.guild_id, warn_actions=default
        )
        await interaction.response.send_message(
            embed=make_embed("✅ Действия за варны сброшены.", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._main_embed(interaction.guild),
            view=SettingsMainView(self.cog, interaction.guild.id)
        )


# ──────────────────────────────────────────────
# Настройки тикетов
# ──────────────────────────────────────────────
class TicketsSettingsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(CategorySelect())

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._main_embed(interaction.guild),
            view=SettingsMainView(self.cog, interaction.guild.id)
        )


class CategorySelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="📁 Выберите категорию для тикетов",
            channel_types=[discord.ChannelType.category],
            min_values=1, max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        await interaction.client.db.update_guild_config(
            interaction.guild_id, ticket_category=cat.id
        )
        await interaction.response.send_message(
            embed=make_embed(f"✅ Категория тикетов: **{cat.name}**", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


# ──────────────────────────────────────────────
# Модальные окна
# ──────────────────────────────────────────────
class PrefixModal(discord.ui.Modal, title="Изменить префикс"):
    prefix = discord.ui.TextInput(
        label="Новый префикс",
        placeholder="Например: !, ?, .",
        max_length=5,
        min_length=1
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.client.db.update_guild_config(
            interaction.guild_id, prefix=self.prefix.value
        )
        await interaction.response.send_message(
            embed=make_embed(f"✅ Префикс изменён на `{self.prefix.value}`", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


class BannedWordModal(discord.ui.Modal, title="Добавить запрещённое слово"):
    word = discord.ui.TextInput(
        label="Слово",
        placeholder="Введите слово для блокировки",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.client.db.add_banned_word(
            interaction.guild_id, self.word.value, interaction.user.id
        )
        await interaction.response.send_message(
            embed=make_embed(f"✅ Слово `{self.word.value}` добавлено в фильтр.", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )


class WarnActionsModal(discord.ui.Modal, title="Действия за предупреждения"):
    actions = discord.ui.TextInput(
        label="JSON: {\"кол-во_варнов\": \"действие\"}",
        style=discord.TextStyle.paragraph,
        placeholder='{"3": "mute_1h", "5": "mute_24h", "7": "kick", "10": "ban"}',
        default='{"3": "mute_1h", "5": "mute_24h", "7": "kick", "10": "ban"}'
    )

    async def on_submit(self, interaction: discord.Interaction):
        import json
        try:
            parsed = json.loads(self.actions.value)
            await interaction.client.db.update_guild_config(
                interaction.guild_id, warn_actions=json.dumps(parsed)
            )
            await interaction.response.send_message(
                embed=make_embed("✅ Действия за варны обновлены.", BotConfig.COLOR_SUCCESS),
                ephemeral=True
            )
        except json.JSONDecodeError:
            await interaction.response.send_message(
                embed=make_embed("❌ Неверный JSON.", BotConfig.COLOR_ERROR),
                ephemeral=True
            )


# ──────────────────────────────────────────────
# Ког настроек
# ──────────────────────────────────────────────
class Settings(commands.Cog):
    """Настройка бота через Discord — каналы, роли, системы."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="settings", description="Открыть панель настроек бота")
    @app_commands.checks.has_permissions(administrator=True)
    async def settings(self, interaction: discord.Interaction):
        await self.bot.db.create_guild_config(interaction.guild_id)
        embed = await self._main_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=SettingsMainView(self, interaction.guild_id), ephemeral=True)

    # ── Embed'ы разделов ──

    async def _main_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title=f"⚙️ Настройки — {guild.name}", color=BotConfig.COLOR_INFO)
        if cfg:
            e.add_field(name="🛡️ Модерация", value="✅" if cfg["mod_enabled"] else "❌", inline=True)
            e.add_field(name="🤖 Автомод",    value="✅" if cfg["automod_enabled"] else "❌", inline=True)
            e.add_field(name="🎫 Тикеты",     value="✅" if cfg["tickets_enabled"] else "❌", inline=True)
            e.add_field(name="📋 Логи",        value="✅" if cfg["logging_enabled"] else "❌", inline=True)
        e.set_footer(text="Выберите раздел для настройки")
        return e

    async def _channels_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title="📋 Настройка каналов", color=BotConfig.COLOR_INFO)
        if cfg:
            def ch(cid): return f"<#{cid}>" if cid else "не задан"
            e.add_field(name="Канал логов",      value=ch(cfg["log_channel"]))
            e.add_field(name="Канал мод-логов",  value=ch(cfg["mod_log_channel"]))
            e.add_field(name="Канал тикетов",    value=ch(cfg["ticket_channel"]))
        return e

    async def _roles_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title="👥 Настройка ролей", color=BotConfig.COLOR_INFO)
        if cfg:
            def ro(rid): return f"<@&{rid}>" if rid else "не задана"
            e.add_field(name="Роль модератора",  value=ro(cfg["mod_role"]))
            e.add_field(name="Роль администратора", value=ro(cfg["admin_role"]))
            e.add_field(name="Роль поддержки",   value=ro(cfg["ticket_support"]))
        return e

    async def _mod_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title="🛡️ Системы модерации", color=BotConfig.COLOR_MOD)
        if cfg:
            e.add_field(name="Модерация",  value="✅ Вкл" if cfg["mod_enabled"] else "❌ Выкл")
            e.add_field(name="Логи",       value="✅ Вкл" if cfg["logging_enabled"] else "❌ Выкл")
            e.add_field(name="Тикеты",     value="✅ Вкл" if cfg["tickets_enabled"] else "❌ Выкл")
        return e

    async def _automod_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title="🤖 Автомодерация", color=BotConfig.COLOR_WARNING)
        if cfg:
            e.add_field(name="Автомод",     value="✅" if cfg["automod_enabled"] else "❌")
            e.add_field(name="Антиспам",    value="✅" if cfg["automod_spam_enabled"] else "❌")
            e.add_field(name="Антиссылки",  value="✅" if cfg["automod_links_enabled"] else "❌")
            e.add_field(name="Капс-фильтр", value="✅" if cfg["automod_caps_enabled"] else "❌")
            e.add_field(name="Фильтр слов", value="✅" if cfg["automod_words_enabled"] else "❌")
            e.add_field(name="Антименшн",   value="✅" if cfg["automod_mentions_enabled"] else "❌")
        return e

    async def _tickets_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title="🎫 Система тикетов", color=BotConfig.COLOR_SUCCESS)
        if cfg:
            e.add_field(name="Статус",    value="✅ Вкл" if cfg["tickets_enabled"] else "❌ Выкл")
            e.add_field(name="Категория", value=f"<#{cfg['ticket_category']}>" if cfg["ticket_category"] else "не задана")
        return e

    async def _warns_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await self.bot.db.get_guild_config(guild.id)
        e = discord.Embed(title="⚠️ Система предупреждений", color=BotConfig.COLOR_WARNING)
        if cfg and cfg["warn_actions"]:
            actions = cfg["warn_actions"]
            for count, action in sorted(actions.items(), key=lambda x: int(x[0])):
                e.add_field(name=f"{count} варнов", value=action, inline=True)
        return e

    # ── Авто-создание каналов ──
    async def _auto_create_channels(self, guild: discord.Guild) -> list:
        """Создаёт каналы для логов и модерации, возвращает их имена."""
        created = []
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False)
        }
        log_ch = await guild.create_text_channel("📋・логи-бота", overwrites=overwrites)
        mod_ch = await guild.create_text_channel("🛡️・мод-логи", overwrites=overwrites)
        await self.bot.db.update_guild_config(
            guild.id,
            log_channel=log_ch.id,
            mod_log_channel=mod_ch.id
        )
        created += [log_ch.name, mod_ch.name]
        return created

    # ── Авто-создание ролей ──
    async def _auto_create_roles(self, guild: discord.Guild) -> list:
        """Создаёт роли модератора и администратора."""
        created = []
        mod_role = await guild.create_role(
            name="Модератор",
            color=discord.Color.blue(),
            permissions=discord.Permissions(
                kick_members=True, ban_members=True, manage_messages=True, moderate_members=True
            )
        )
        admin_role = await guild.create_role(
            name="Администратор",
            color=discord.Color.red(),
            permissions=discord.Permissions(administrator=True)
        )
        await self.bot.db.update_guild_config(
            guild.id, mod_role=mod_role.id, admin_role=admin_role.id
        )
        created += [mod_role.name, admin_role.name]
        return created


async def setup(bot):
    await bot.add_cog(Settings(bot))
