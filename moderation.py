"""
cogs/moderation.py — Основные команды модерации.
Мут реализован через Discord Timeout (не роль!).
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timedelta, timezone
from utils.config import BotConfig
from utils.helpers import (
    parse_duration, format_duration, make_embed,
    has_mod_perms, has_admin_perms
)

log = logging.getLogger("moderation")


class Moderation(commands.Cog):
    """Система модерации: бан, кик, мут (timeout), варн."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = BotConfig()

    # ──────────────────────────────────────────
    # Проверка: включена ли модерация на сервере
    # ──────────────────────────────────────────
    async def _check_mod_enabled(self, interaction: discord.Interaction) -> bool:
        cfg = await self.bot.db.get_guild_config(interaction.guild_id)
        if cfg and not cfg["mod_enabled"]:
            await interaction.response.send_message(
                embed=make_embed("❌ Модерация отключена на этом сервере.", BotConfig.COLOR_ERROR),
                ephemeral=True
            )
            return False
        return True

    # ──────────────────────────────────────────
    # Отправка лога в канал модерации
    # ──────────────────────────────────────────
    async def _send_mod_log(
        self, guild: discord.Guild, action: str,
        target: discord.Member | discord.User,
        moderator: discord.Member,
        reason: str, duration: str = None, case_id: int = None
    ):
        cfg = await self.bot.db.get_guild_config(guild.id)
        if not cfg or not cfg["mod_log_channel"]:
            return
        channel = guild.get_channel(cfg["mod_log_channel"])
        if not channel:
            return

        emoji_map = {
            "ban": BotConfig.EMOJI_BAN,
            "kick": BotConfig.EMOJI_KICK,
            "mute": BotConfig.EMOJI_MUTE,
            "warn": BotConfig.EMOJI_WARN,
            "unban": BotConfig.EMOJI_UNBAN,
            "unmute": BotConfig.EMOJI_UNMUTE,
        }
        emoji = emoji_map.get(action, "📋")
        color_map = {
            "ban": BotConfig.COLOR_ERROR,
            "kick": BotConfig.COLOR_WARNING,
            "mute": BotConfig.COLOR_WARNING,
            "warn": BotConfig.COLOR_WARNING,
            "unban": BotConfig.COLOR_SUCCESS,
            "unmute": BotConfig.COLOR_SUCCESS,
        }
        color = color_map.get(action, BotConfig.COLOR_INFO)

        embed = discord.Embed(
            title=f"{emoji} {action.upper()} | Кейс #{case_id}",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="👤 Пользователь", value=f"{target.mention} (`{target.id}`)", inline=True)
        embed.add_field(name="🛡️ Модератор",   value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
        if duration:
            embed.add_field(name="⏱️ Длительность", value=duration, inline=True)
        embed.add_field(name="📝 Причина", value=reason or "Не указана", inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        await channel.send(embed=embed)

    # ──────────────────────────────────────────
    # /ban
    # ──────────────────────────────────────────
    @app_commands.command(name="ban", description="Заблокировать пользователя на сервере")
    @app_commands.describe(
        member="Пользователь для бана",
        reason="Причина бана",
        delete_days="Удалить сообщения за N дней (0-7)"
    )
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(
        self, interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Не указана",
        delete_days: int = 0
    ):
        if not await self._check_mod_enabled(interaction):
            return
        await interaction.response.defer(ephemeral=False)

        # Нельзя забанить себя или бота
        if member == interaction.user:
            return await interaction.followup.send(
                embed=make_embed("❌ Нельзя забанить самого себя.", BotConfig.COLOR_ERROR)
            )
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.followup.send(
                embed=make_embed("❌ Нельзя банить пользователей с ролью выше или равной вашей.", BotConfig.COLOR_ERROR)
            )

        # Уведомляем пользователя в ЛС перед баном
        try:
            dm_embed = discord.Embed(
                title=f"🔨 Вы забанены на {interaction.guild.name}",
                description=f"**Причина:** {reason}",
                color=BotConfig.COLOR_ERROR
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # ЛС закрыты — это нормально

        await member.ban(reason=f"[{interaction.user}] {reason}", delete_message_days=min(delete_days, 7))

        case_id = await self.bot.db.add_mod_action(
            interaction.guild_id, member.id, interaction.user.id, "ban", reason
        )
        await self._send_mod_log(
            interaction.guild, "ban", member, interaction.user, reason, case_id=case_id
        )
        await interaction.followup.send(
            embed=make_embed(
                f"{BotConfig.EMOJI_BAN} **{member}** забанен. Причина: {reason}",
                BotConfig.COLOR_SUCCESS
            )
        )

    # ──────────────────────────────────────────
    # /unban
    # ──────────────────────────────────────────
    @app_commands.command(name="unban", description="Разблокировать пользователя")
    @app_commands.describe(user_id="ID пользователя для разбана", reason="Причина разбана")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(
        self, interaction: discord.Interaction,
        user_id: str,
        reason: str = "Не указана"
    ):
        if not await self._check_mod_enabled(interaction):
            return
        await interaction.response.defer()
        try:
            uid = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"[{interaction.user}] {reason}")
            case_id = await self.bot.db.add_mod_action(
                interaction.guild_id, uid, interaction.user.id, "unban", reason
            )
            await self._send_mod_log(
                interaction.guild, "unban", user, interaction.user, reason, case_id=case_id
            )
            await interaction.followup.send(
                embed=make_embed(f"✅ **{user}** разбанен.", BotConfig.COLOR_SUCCESS)
            )
        except (ValueError, discord.NotFound):
            await interaction.followup.send(
                embed=make_embed("❌ Пользователь не найден или не заблокирован.", BotConfig.COLOR_ERROR)
            )

    # ──────────────────────────────────────────
    # /kick
    # ──────────────────────────────────────────
    @app_commands.command(name="kick", description="Выгнать пользователя с сервера")
    @app_commands.describe(member="Пользователь для кика", reason="Причина")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Не указана"
    ):
        if not await self._check_mod_enabled(interaction):
            return
        await interaction.response.defer()

        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.followup.send(
                embed=make_embed("❌ Нельзя кикнуть пользователя с ролью выше или равной вашей.", BotConfig.COLOR_ERROR)
            )
        try:
            dm_embed = discord.Embed(
                title=f"👢 Вы исключены с {interaction.guild.name}",
                description=f"**Причина:** {reason}",
                color=BotConfig.COLOR_WARNING
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        await member.kick(reason=f"[{interaction.user}] {reason}")
        case_id = await self.bot.db.add_mod_action(
            interaction.guild_id, member.id, interaction.user.id, "kick", reason
        )
        await self._send_mod_log(
            interaction.guild, "kick", member, interaction.user, reason, case_id=case_id
        )
        await interaction.followup.send(
            embed=make_embed(
                f"{BotConfig.EMOJI_KICK} **{member}** исключён. Причина: {reason}",
                BotConfig.COLOR_SUCCESS
            )
        )

    # ──────────────────────────────────────────
    # /mute — через Discord Timeout (не роль!)
    # ──────────────────────────────────────────
    @app_commands.command(name="mute", description="Замутить пользователя через тайм-аут")
    @app_commands.describe(
        member="Пользователь",
        duration="Длительность: 10m, 1h, 2d (макс. 28d)",
        reason="Причина"
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(
        self, interaction: discord.Interaction,
        member: discord.Member,
        duration: str = "1h",
        reason: str = "Не указана"
    ):
        if not await self._check_mod_enabled(interaction):
            return
        await interaction.response.defer()

        seconds = parse_duration(duration)  # переводим "1h" → секунды
        if not seconds:
            return await interaction.followup.send(
                embed=make_embed("❌ Неверный формат времени. Пример: `10m`, `2h`, `1d`", BotConfig.COLOR_ERROR)
            )
        if seconds > BotConfig.MAX_TIMEOUT_SECONDS:
            return await interaction.followup.send(
                embed=make_embed("❌ Максимальное время мута — 28 дней.", BotConfig.COLOR_ERROR)
            )

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)

        # ── Ключевой вызов: Discord Timeout ──
        await member.timeout(expires_at, reason=f"[{interaction.user}] {reason}")

        case_id = await self.bot.db.add_mod_action(
            interaction.guild_id, member.id, interaction.user.id,
            "mute", reason, duration=seconds, expires_at=expires_at
        )
        dur_str = format_duration(seconds)
        await self._send_mod_log(
            interaction.guild, "mute", member, interaction.user,
            reason, duration=dur_str, case_id=case_id
        )
        try:
            dm = discord.Embed(
                title=f"🔇 Вы замучены на {interaction.guild.name}",
                description=f"**Длительность:** {dur_str}\n**Причина:** {reason}",
                color=BotConfig.COLOR_WARNING
            )
            await member.send(embed=dm)
        except discord.Forbidden:
            pass
        await interaction.followup.send(
            embed=make_embed(
                f"{BotConfig.EMOJI_MUTE} **{member}** замучен на {dur_str}. Причина: {reason}",
                BotConfig.COLOR_SUCCESS
            )
        )

    # ──────────────────────────────────────────
    # /unmute
    # ──────────────────────────────────────────
    @app_commands.command(name="unmute", description="Снять мут с пользователя")
    @app_commands.describe(member="Пользователь", reason="Причина")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(
        self, interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Не указана"
    ):
        if not await self._check_mod_enabled(interaction):
            return
        await interaction.response.defer()
        await member.timeout(None, reason=f"[{interaction.user}] {reason}")
        case_id = await self.bot.db.add_mod_action(
            interaction.guild_id, member.id, interaction.user.id, "unmute", reason
        )
        await self._send_mod_log(
            interaction.guild, "unmute", member, interaction.user, reason, case_id=case_id
        )
        await interaction.followup.send(
            embed=make_embed(f"{BotConfig.EMOJI_UNMUTE} Мут снят с **{member}**.", BotConfig.COLOR_SUCCESS)
        )

    # ──────────────────────────────────────────
    # /warn
    # ──────────────────────────────────────────
    @app_commands.command(name="warn", description="Выдать предупреждение пользователю")
    @app_commands.describe(member="Пользователь", reason="Причина")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn(
        self, interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Не указана"
    ):
        if not await self._check_mod_enabled(interaction):
            return
        await interaction.response.defer()

        # Добавляем варн и узнаём сколько их теперь
        warn_count = await self.bot.db.add_warning(
            interaction.guild_id, member.id, interaction.user.id, reason
        )
        await self.bot.db.add_mod_action(
            interaction.guild_id, member.id, interaction.user.id, "warn", reason
        )

        # Проверяем автоматические действия за варны
        cfg = await self.bot.db.get_guild_config(interaction.guild_id)
        warn_actions = cfg["warn_actions"] if cfg else {}
        auto_action = warn_actions.get(str(warn_count))
        auto_msg = ""

        if auto_action:
            auto_msg = await self._apply_auto_warn_action(
                interaction, member, auto_action, warn_count
            )

        try:
            dm = discord.Embed(
                title=f"⚠️ Предупреждение на {interaction.guild.name}",
                description=f"**Причина:** {reason}\n**Всего предупреждений:** {warn_count}",
                color=BotConfig.COLOR_WARNING
            )
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        embed = discord.Embed(
            title=f"⚠️ Предупреждение выдано",
            color=BotConfig.COLOR_WARNING
        )
        embed.add_field(name="Пользователь", value=member.mention)
        embed.add_field(name="Причина", value=reason)
        embed.add_field(name="Всего варнов", value=str(warn_count))
        if auto_msg:
            embed.add_field(name="⚡ Автодействие", value=auto_msg, inline=False)
        await interaction.followup.send(embed=embed)

    async def _apply_auto_warn_action(
        self, interaction: discord.Interaction,
        member: discord.Member, action: str, warn_count: int
    ) -> str:
        """Применяет автоматическое действие за накопленные варны."""
        reason = f"Автоматически: {warn_count} предупреждений"
        if action == "kick":
            await member.kick(reason=reason)
            return "Пользователь исключён с сервера"
        elif action == "ban":
            await member.ban(reason=reason)
            return "Пользователь забанен"
        elif action.startswith("mute_"):
            dur_map = {"mute_1h": 3600, "mute_24h": 86400, "mute_7d": 604800}
            seconds = dur_map.get(action, 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            await member.timeout(expires_at, reason=reason)
            return f"Пользователь замучен на {format_duration(seconds)}"
        return ""

    # ──────────────────────────────────────────
    # /warnings — история варнов
    # ──────────────────────────────────────────
    @app_commands.command(name="warnings", description="Посмотреть варны пользователя")
    @app_commands.describe(member="Пользователь")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        warns = await self.bot.db.get_active_warnings(interaction.guild_id, member.id)

        embed = discord.Embed(
            title=f"⚠️ Предупреждения — {member}",
            color=BotConfig.COLOR_WARNING
        )
        if not warns:
            embed.description = "Нет активных предупреждений."
        else:
            for w in warns:
                embed.add_field(
                    name=f"#{w['id']} | {w['created_at'].strftime('%d.%m.%Y %H:%M')}",
                    value=f"**Модератор:** <@{w['mod_id']}>\n**Причина:** {w['reason'] or 'Не указана'}",
                    inline=False
                )
        await interaction.followup.send(embed=embed)

    # ──────────────────────────────────────────
    # /clearwarns — снять все варны
    # ──────────────────────────────────────────
    @app_commands.command(name="clearwarns", description="Снять все предупреждения пользователя")
    @app_commands.describe(member="Пользователь")
    @app_commands.checks.has_permissions(ban_members=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        await self.bot.db.clear_warnings(interaction.guild_id, member.id, interaction.user.id)
        await interaction.followup.send(
            embed=make_embed(f"✅ Все варны **{member}** сняты.", BotConfig.COLOR_SUCCESS)
        )

    # ──────────────────────────────────────────
    # /history — история всех наказаний
    # ──────────────────────────────────────────
    @app_commands.command(name="history", description="История наказаний пользователя")
    @app_commands.describe(member="Пользователь")
    @app_commands.checks.has_permissions(kick_members=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        actions = await self.bot.db.get_user_history(interaction.guild_id, member.id)

        pages = []
        chunk = []
        for i, a in enumerate(actions):
            chunk.append(a)
            if len(chunk) == 5 or i == len(actions) - 1:
                embed = discord.Embed(
                    title=f"📋 История — {member}",
                    description=f"Всего записей: {len(actions)}",
                    color=BotConfig.COLOR_INFO
                )
                for rec in chunk:
                    embed.add_field(
                        name=f"[{rec['action'].upper()}] {rec['created_at'].strftime('%d.%m.%Y %H:%M')}",
                        value=f"Модератор: <@{rec['mod_id']}> | Причина: {rec['reason'] or '—'}",
                        inline=False
                    )
                pages.append(embed)
                chunk = []

        if not pages:
            await interaction.followup.send(
                embed=make_embed("Нет записей о наказаниях.", BotConfig.COLOR_INFO)
            )
        else:
            # Пагинация с кнопками
            view = PaginationView(pages)
            await interaction.followup.send(embed=pages[0], view=view)

    # ──────────────────────────────────────────
    # /purge — массовое удаление сообщений
    # ──────────────────────────────────────────
    @app_commands.command(name="purge", description="Удалить N последних сообщений")
    @app_commands.describe(amount="Количество сообщений (1-100)", member="Только от этого пользователя (опционально)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self, interaction: discord.Interaction,
        amount: int,
        member: discord.Member = None
    ):
        await interaction.response.defer(ephemeral=True)
        amount = max(1, min(amount, 100))

        def check(msg):
            return member is None or msg.author == member

        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(
            embed=make_embed(f"🗑️ Удалено {len(deleted)} сообщений.", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )

    # Обработчик ошибок для команд
    @ban.error
    @kick.error
    @mute.error
    async def mod_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                embed=make_embed("❌ Недостаточно прав.", BotConfig.COLOR_ERROR),
                ephemeral=True
            )


# ──────────────────────────────────────────────
# Вьюха с кнопками для пагинации
# ──────────────────────────────────────────────
class PaginationView(discord.ui.View):
    def __init__(self, pages: list):
        super().__init__(timeout=120)
        self.pages = pages
        self.current = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.page_btn.label = f"{self.current + 1} / {len(self.pages)}"

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
