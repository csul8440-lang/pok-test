"""
cogs/tickets.py — Полная система тикетов с кнопками.
Пользователи создают тикеты, поддержка отвечает, закрывает с транскриптом.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime, timezone
from utils.config import BotConfig
from utils.helpers import make_embed

log = logging.getLogger("tickets")


# ──────────────────────────────────────────────
# Модальное окно: тема тикета
# ──────────────────────────────────────────────
class TicketModal(discord.ui.Modal, title="Создать тикет"):
    subject = discord.ui.TextInput(
        label="Тема обращения",
        placeholder="Опишите кратко вашу проблему...",
        max_length=100,
        required=True
    )
    description = discord.ui.TextInput(
        label="Подробное описание",
        style=discord.TextStyle.paragraph,
        placeholder="Опишите проблему подробнее...",
        max_length=1000,
        required=False
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._create_ticket(
            interaction,
            subject=self.subject.value,
            description=self.description.value
        )


# ──────────────────────────────────────────────
# Кнопка "Создать тикет" (постоянная, persist)
# ──────────────────────────────────────────────
class TicketCreateView(discord.ui.View):
    """Постоянная кнопка. custom_id должен быть уникальным и неменяющимся."""

    def __init__(self):
        super().__init__(timeout=None)  # timeout=None → кнопка работает вечно

    @discord.ui.button(
        label="🎫 Создать тикет",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:create"   # постоянный ID — бот узнаёт кнопку после перезапуска
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Получаем ког через бота
        cog = interaction.client.cogs.get("Tickets")
        if cog:
            await interaction.response.send_modal(TicketModal(cog))


# ──────────────────────────────────────────────
# Кнопки управления тикетом (внутри канала)
# ──────────────────────────────────────────────
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔒 Закрыть тикет",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs.get("Tickets")
        if cog:
            await cog._close_ticket(interaction)

    @discord.ui.button(
        label="📋 Транскрипт",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:transcript"
    )
    async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.cogs.get("Tickets")
        if cog:
            await cog._send_transcript(interaction)

    @discord.ui.button(
        label="➕ Добавить участника",
        style=discord.ButtonStyle.success,
        custom_id="ticket:add_user"
    )
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Упомяните пользователя, которого хотите добавить:",
            ephemeral=True
        )


class Tickets(commands.Cog):
    """Система тикетов с модальными окнами и кнопками."""

    def __init__(self, bot):
        self.bot = bot
        # Регистрируем постоянные вьюхи (работают после перезапуска)
        bot.add_view(TicketCreateView())
        bot.add_view(TicketControlView())

    # ──────────────────────────────────────────
    # /ticket setup — разместить панель тикетов
    # ──────────────────────────────────────────
    @app_commands.command(name="ticket-setup", description="Разместить панель создания тикетов")
    @app_commands.describe(channel="Канал для панели (по умолчанию — текущий)")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None
    ):
        await interaction.response.defer(ephemeral=True)
        cfg = await self.bot.db.get_guild_config(interaction.guild_id)

        if not cfg or not cfg["tickets_enabled"]:
            return await interaction.followup.send(
                embed=make_embed("❌ Система тикетов отключена.", BotConfig.COLOR_ERROR)
            )

        target = channel or interaction.channel
        embed = discord.Embed(
            title="🎫 Служба поддержки",
            description=(
                "Нажмите кнопку ниже, чтобы создать тикет.\n\n"
                "Наши модераторы ответят вам как можно скорее.\n"
                "Пожалуйста, описывайте проблему максимально подробно."
            ),
            color=BotConfig.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

        # Отправляем панель с постоянной кнопкой
        msg = await target.send(embed=embed, view=TicketCreateView())

        # Сохраняем канал тикетов в конфиг
        await self.bot.db.update_guild_config(
            interaction.guild_id, ticket_channel=target.id
        )
        await interaction.followup.send(
            embed=make_embed(f"✅ Панель тикетов размещена в {target.mention}", BotConfig.COLOR_SUCCESS)
        )

    # ──────────────────────────────────────────
    # Внутренний метод создания тикета
    # ──────────────────────────────────────────
    async def _create_ticket(
        self,
        interaction: discord.Interaction,
        subject: str,
        description: str = None
    ):
        await interaction.response.defer(ephemeral=True)
        cfg = await self.bot.db.get_guild_config(interaction.guild_id)

        if not cfg or not cfg["tickets_enabled"]:
            return await interaction.followup.send("❌ Тикеты отключены.", ephemeral=True)

        # Проверяем лимит: 1 открытый тикет на пользователя
        open_count = await self.bot.db.get_user_open_tickets(
            interaction.guild_id, interaction.user.id
        )
        if open_count >= 1:
            return await interaction.followup.send(
                embed=make_embed("❌ У вас уже есть открытый тикет.", BotConfig.COLOR_ERROR),
                ephemeral=True
            )

        guild = interaction.guild
        # Определяем категорию для тикет-каналов
        category = None
        if cfg["ticket_category"]:
            category = guild.get_channel(cfg["ticket_category"])

        # Узнаём следующий номер заранее
        ticket_num_preview = await self.bot.db._fetchval(
            "SELECT COALESCE(MAX(ticket_num), 0) + 1 FROM tickets WHERE guild_id = ?",
            (guild.id,)
        )

        # Создаём приватный канал для тикета
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, attach_files=True
            ),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        # Добавляем роль поддержки, если настроена
        if cfg["ticket_support"]:
            support_role = guild.get_role(cfg["ticket_support"])
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True
                )

        channel = await guild.create_text_channel(
            name=f"ticket-{ticket_num_preview:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"Тикет #{ticket_num_preview:04d} | {interaction.user} | {subject}"
        )

        # Сохраняем в БД
        ticket_num = await self.bot.db.create_ticket(
            guild.id, channel.id, interaction.user.id, subject
        )

        # Приветственный embed в канале тикета
        embed = discord.Embed(
            title=f"🎫 Тикет #{ticket_num:04d}",
            description=(
                f"**Создатель:** {interaction.user.mention}\n"
                f"**Тема:** {subject}\n"
                f"**Описание:** {description or 'Не указано'}\n\n"
                "Поддержка ответит вам в ближайшее время.\n"
                "Используйте кнопки ниже для управления тикетом."
            ),
            color=BotConfig.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await channel.send(
            content=interaction.user.mention,
            embed=embed,
            view=TicketControlView()
        )

        await interaction.followup.send(
            embed=make_embed(f"✅ Тикет создан: {channel.mention}", BotConfig.COLOR_SUCCESS),
            ephemeral=True
        )
        log.info(f"Тикет #{ticket_num} создан пользователем {interaction.user} на {guild.name}")

    # ──────────────────────────────────────────
    # Закрытие тикета
    # ──────────────────────────────────────────
    async def _close_ticket(self, interaction: discord.Interaction):
        ticket = await self.bot.db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            return await interaction.response.send_message(
                "❌ Это не канал тикета.", ephemeral=True
            )
        if ticket["status"] != "open":
            return await interaction.response.send_message(
                "❌ Тикет уже закрыт.", ephemeral=True
            )

        await interaction.response.defer()

        # Показываем подтверждение
        confirm_view = TicketCloseConfirmView(self, ticket)
        await interaction.followup.send(
            embed=make_embed("Вы уверены, что хотите закрыть тикет?", BotConfig.COLOR_WARNING),
            view=confirm_view
        )

    # ──────────────────────────────────────────
    # Транскрипт тикета
    # ──────────────────────────────────────────
    async def _send_transcript(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket = await self.bot.db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            return await interaction.followup.send("❌ Канал не является тикетом.", ephemeral=True)

        # Собираем историю сообщений
        messages = []
        async for msg in interaction.channel.history(limit=200, oldest_first=True):
            if msg.author.bot:
                continue
            messages.append(f"[{msg.created_at.strftime('%d.%m.%Y %H:%M')}] {msg.author}: {msg.content}")

        transcript_text = "\n".join(messages) or "Нет сообщений."
        # Отправляем как файл
        file = discord.File(
            fp=__import__("io").BytesIO(transcript_text.encode()),
            filename=f"ticket-{ticket['ticket_num']:04d}-transcript.txt"
        )
        await interaction.followup.send(
            embed=make_embed("📋 Транскрипт тикета", BotConfig.COLOR_INFO),
            file=file,
            ephemeral=True
        )

    # ──────────────────────────────────────────
    # /ticket add — добавить пользователя вручную
    # ──────────────────────────────────────────
    @app_commands.command(name="ticket-add", description="Добавить пользователя в тикет")
    @app_commands.describe(member="Пользователь")
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        ticket = await self.bot.db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            return await interaction.response.send_message("❌ Это не канал тикета.", ephemeral=True)
        await interaction.channel.set_permissions(
            member,
            read_messages=True,
            send_messages=True
        )
        await interaction.response.send_message(
            embed=make_embed(f"✅ {member.mention} добавлен в тикет.", BotConfig.COLOR_SUCCESS)
        )

    # ──────────────────────────────────────────
    # /ticket remove — убрать пользователя
    # ──────────────────────────────────────────
    @app_commands.command(name="ticket-remove", description="Убрать пользователя из тикета")
    @app_commands.describe(member="Пользователь")
    async def ticket_remove(self, interaction: discord.Interaction, member: discord.Member):
        ticket = await self.bot.db.get_ticket_by_channel(interaction.channel_id)
        if not ticket:
            return await interaction.response.send_message("❌ Это не канал тикета.", ephemeral=True)
        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(
            embed=make_embed(f"✅ {member.mention} удалён из тикета.", BotConfig.COLOR_SUCCESS)
        )


# ──────────────────────────────────────────────
# Подтверждение закрытия тикета
# ──────────────────────────────────────────────
class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, cog: Tickets, ticket):
        super().__init__(timeout=60)
        self.cog = cog
        self.ticket = ticket

    @discord.ui.button(label="✅ Да, закрыть", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.bot.db.close_ticket(interaction.channel_id, interaction.user.id)

        # Отключаем возможность писать для создателя тикета
        creator = interaction.guild.get_member(self.ticket["user_id"])
        if creator:
            await interaction.channel.set_permissions(creator, send_messages=False)

        embed = discord.Embed(
            title="🔒 Тикет закрыт",
            description=f"Закрыт: {interaction.user.mention}\nВремя: {discord.utils.format_dt(discord.utils.utcnow())}",
            color=BotConfig.COLOR_ERROR
        )
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)

        # Через 10 секунд удаляем канал
        import asyncio
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason="Тикет закрыт")
        except Exception:
            pass

    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            embed=make_embed("Закрытие отменено.", BotConfig.COLOR_INFO),
            view=None
        )


async def setup(bot):
    await bot.add_cog(Tickets(bot))
