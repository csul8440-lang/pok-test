"""
utils/database.py — Полный слой работы с SQLite через aiosqlite.
SQLite не требует отдельного сервера — файл БД хранится локально.

Ключевые отличия от PostgreSQL-версии:
  • Плейсхолдеры: ? вместо $1, $2, ...
  • Нет SERIAL — используем INTEGER PRIMARY KEY (автоинкремент SQLite)
  • Нет JSONB — храним JSON как TEXT, парсим вручную
  • Нет TIMESTAMPTZ — используем TEXT в формате ISO-8601
  • Нет пула соединений — одно соединение с WAL-режимом
  • UPSERT через INSERT OR REPLACE / ON CONFLICT DO UPDATE
  • Булевы значения: 1/0 вместо TRUE/FALSE
"""

import aiosqlite
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List

log = logging.getLogger("database")

# Путь к файлу БД (создаётся автоматически)
DB_PATH = "data/modbot.db"


def _now() -> str:
    """Текущее время в ISO-8601 UTC — используется вместо NOW() в SQLite."""
    return datetime.now(timezone.utc).isoformat()


class Row(dict):
    """
    Обёртка над sqlite3.Row — позволяет обращаться по ключу,
    как в asyncpg.Record: row["field"] и row.get("field").
    """
    pass


def _row(cursor_row) -> Optional[Row]:
    """Конвертирует одну sqlite3.Row в Row-словарь."""
    if cursor_row is None:
        return None
    return Row(dict(cursor_row))


def _rows(cursor_rows) -> List[Row]:
    """Конвертирует список sqlite3.Row в список Row-словарей."""
    return [Row(dict(r)) for r in cursor_rows]


class Database:
    """
    Асинхронная обёртка над aiosqlite.
    Одно соединение на весь процесс в режиме WAL
    (Write-Ahead Logging) для лучшей конкурентности.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn: aiosqlite.Connection = None  # единственное соединение

    # ──────────────────────────────────────────
    # Подключение и инициализация
    # ──────────────────────────────────────────

    async def connect(self):
        """Открывает соединение с БД и включает WAL + внешние ключи."""
        import os
        os.makedirs("data", exist_ok=True)  # создаём папку data/ если нет

        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row  # доступ по имени столбца

        # WAL — позволяет читать одновременно с записью
        await self.conn.execute("PRAGMA journal_mode=WAL")
        # Включаем поддержку внешних ключей (в SQLite по умолчанию выкл.)
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.commit()
        log.info(f"SQLite подключён: {self.db_path} (WAL-режим)")

    async def disconnect(self):
        if self.conn:
            await self.conn.close()

    async def init_tables(self):
        """Создаёт все таблицы, если они не существуют."""
        await self.conn.executescript("""
            -- ────────────────────────────────────────
            -- Конфигурация серверов Discord
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id        INTEGER PRIMARY KEY,   -- ID сервера Discord

                prefix          TEXT    DEFAULT '!',
                lang            TEXT    DEFAULT 'ru',

                -- Каналы (хранятся как INTEGER — ID канала)
                log_channel     INTEGER,               -- канал общих логов
                mod_log_channel INTEGER,               -- канал логов модерации
                ticket_channel  INTEGER,               -- канал с кнопкой тикета
                ticket_category INTEGER,               -- категория тикет-каналов

                -- Роли
                mute_role       INTEGER,               -- резервная роль мута
                mod_role        INTEGER,               -- роль модератора
                admin_role      INTEGER,               -- роль администратора
                ticket_support  INTEGER,               -- роль поддержки тикетов

                -- Переключатели (1=вкл, 0=выкл)
                mod_enabled              INTEGER DEFAULT 1,
                automod_enabled          INTEGER DEFAULT 1,
                tickets_enabled          INTEGER DEFAULT 1,
                logging_enabled          INTEGER DEFAULT 1,

                -- Настройки автомодерации
                automod_spam_enabled     INTEGER DEFAULT 1,
                automod_links_enabled    INTEGER DEFAULT 0,
                automod_caps_enabled     INTEGER DEFAULT 1,
                automod_words_enabled    INTEGER DEFAULT 1,
                automod_mentions_enabled INTEGER DEFAULT 1,
                automod_spam_limit       INTEGER DEFAULT 5,
                automod_caps_percent     INTEGER DEFAULT 70,
                automod_mention_limit    INTEGER DEFAULT 5,

                -- JSON-строка: {"3":"mute_1h","5":"mute_24h","7":"kick","10":"ban"}
                warn_actions    TEXT DEFAULT '{"3":"mute_1h","5":"mute_24h","7":"kick","10":"ban"}',

                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            -- ────────────────────────────────────────
            -- Запрещённые слова (на каждый сервер свои)
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS banned_words (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                word        TEXT    NOT NULL,
                added_by    INTEGER,                          -- кто добавил (ID модератора)
                added_at    TEXT    DEFAULT (datetime('now')),
                UNIQUE(guild_id, word)                        -- слово уникально на сервер
            );

            -- ────────────────────────────────────────
            -- История всех действий модерации
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS mod_actions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,   -- кого наказали
                mod_id      INTEGER NOT NULL,   -- кто наказал
                action      TEXT    NOT NULL,   -- ban/kick/mute/warn/unban/unmute
                reason      TEXT,
                duration    INTEGER,            -- длительность мута в секундах
                expires_at  TEXT,              -- ISO-8601, когда истекает
                active      INTEGER DEFAULT 1, -- 1=активно, 0=снято/истекло
                created_at  TEXT    DEFAULT (datetime('now'))
            );
            -- Индексы для быстрой выборки истории
            CREATE INDEX IF NOT EXISTS idx_mod_guild_user ON mod_actions(guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_mod_guild_mod  ON mod_actions(guild_id, mod_id);

            -- ────────────────────────────────────────
            -- Предупреждения (варны)
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                reason      TEXT,
                active      INTEGER DEFAULT 1,  -- 1=активный, 0=снят модератором
                created_at  TEXT    DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_warn_guild_user ON warnings(guild_id, user_id);

            -- ────────────────────────────────────────
            -- Тикеты поддержки
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                channel_id  INTEGER NOT NULL UNIQUE,  -- ID Discord-канала тикета
                user_id     INTEGER NOT NULL,          -- кто создал тикет
                ticket_num  INTEGER NOT NULL,          -- порядковый номер на сервере
                subject     TEXT,                      -- тема обращения
                status      TEXT    DEFAULT 'open',    -- open / closed / deleted
                closed_by   INTEGER,                   -- кто закрыл
                created_at  TEXT    DEFAULT (datetime('now')),
                closed_at   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_guild  ON tickets(guild_id);
            CREATE INDEX IF NOT EXISTS idx_ticket_user   ON tickets(guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_ticket_status ON tickets(guild_id, status);

            -- ────────────────────────────────────────
            -- Сообщения тикетов (для транскрипта)
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                user_id     INTEGER NOT NULL,
                content     TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            -- ────────────────────────────────────────
            -- Статистика действий модераторов
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS mod_stats (
                guild_id    INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                bans        INTEGER DEFAULT 0,
                kicks       INTEGER DEFAULT 0,
                mutes       INTEGER DEFAULT 0,
                warns       INTEGER DEFAULT 0,
                unbans      INTEGER DEFAULT 0,
                unmutes     INTEGER DEFAULT 0,
                updated_at  TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (guild_id, mod_id)  -- одна строка на пару сервер+мод
            );

            -- ────────────────────────────────────────
            -- Белый список разрешённых доменов (для фильтра ссылок)
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS allowed_links (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                domain   TEXT    NOT NULL,
                UNIQUE(guild_id, domain)
            );

            -- ────────────────────────────────────────
            -- Каналы, игнорируемые автомодератором
            -- ────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS automod_ignore (
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );
        """)
        await self.conn.commit()
        log.info("Все таблицы SQLite инициализированы.")

    # ──────────────────────────────────────────
    # Вспомогательные методы выполнения запросов
    # ──────────────────────────────────────────

    async def _execute(self, sql: str, params: tuple = ()):
        """Выполняет INSERT/UPDATE/DELETE, коммитит транзакцию."""
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[Row]:
        """Возвращает одну строку или None."""
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
            return _row(row)

    async def _fetchall(self, sql: str, params: tuple = ()) -> List[Row]:
        """Возвращает список строк."""
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return _rows(rows)

    async def _fetchval(self, sql: str, params: tuple = ()):
        """Возвращает значение первого столбца первой строки."""
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def _lastrowid(self, sql: str, params: tuple = ()) -> int:
        """Выполняет INSERT и возвращает ID вставленной строки."""
        async with self.conn.execute(sql, params) as cur:
            await self.conn.commit()
            return cur.lastrowid

    # ──────────────────────────────────────────
    # guild_config — методы
    # ──────────────────────────────────────────

    async def create_guild_config(self, guild_id: int):
        """Создаёт конфиг сервера если его нет."""
        await self._execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)",
            (guild_id,)
        )

    async def get_guild_config(self, guild_id: int) -> Optional[Row]:
        row = await self._fetchone(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        if row and row.get("warn_actions"):
            # Десериализуем JSON-строку в словарь
            try:
                row["warn_actions"] = json.loads(row["warn_actions"])
            except (json.JSONDecodeError, TypeError):
                row["warn_actions"] = {}
        return row

    async def update_guild_config(self, guild_id: int, **kwargs):
        """Обновляет произвольные поля конфига. Значения булевых → 0/1."""
        if not kwargs:
            return
        await self.create_guild_config(guild_id)

        # Если передаётся warn_actions как dict — сериализуем в JSON
        if "warn_actions" in kwargs and isinstance(kwargs["warn_actions"], dict):
            kwargs["warn_actions"] = json.dumps(kwargs["warn_actions"])

        # Булевы в SQLite хранятся как INTEGER 0/1
        converted = {}
        for k, v in kwargs.items():
            converted[k] = int(v) if isinstance(v, bool) else v

        cols = list(converted.keys())
        vals = list(converted.values())
        # SET col1=?, col2=?, updated_at=datetime('now')
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        set_clause += ", updated_at = datetime('now')"
        sql = f"UPDATE guild_config SET {set_clause} WHERE guild_id = ?"
        await self._execute(sql, (*vals, guild_id))

    async def get_guild_prefix(self, guild_id: int) -> str:
        val = await self._fetchval(
            "SELECT prefix FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        return val or "!"

    # ──────────────────────────────────────────
    # mod_actions — методы
    # ──────────────────────────────────────────

    async def add_mod_action(
        self,
        guild_id: int, user_id: int, mod_id: int,
        action: str, reason: str = None,
        duration: int = None, expires_at: datetime = None
    ) -> int:
        """Добавляет запись модерации и обновляет статистику. Возвращает ID."""
        expires_str = expires_at.isoformat() if expires_at else None
        row_id = await self._lastrowid("""
            INSERT INTO mod_actions
                (guild_id, user_id, mod_id, action, reason, duration, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, mod_id, action, reason, duration, expires_str))

        # Обновляем счётчик в статистике модератора
        await self._increment_mod_stat(guild_id, mod_id, action)
        return row_id

    async def _increment_mod_stat(self, guild_id: int, mod_id: int, action: str):
        """Создаёт строку статистики или увеличивает нужный счётчик."""
        col_map = {
            "ban": "bans", "kick": "kicks", "mute": "mutes",
            "warn": "warns", "unban": "unbans", "unmute": "unmutes"
        }
        col = col_map.get(action)
        if not col:
            return
        # INSERT OR IGNORE создаёт строку, UPDATE увеличивает счётчик
        await self._execute(
            "INSERT OR IGNORE INTO mod_stats (guild_id, mod_id) VALUES (?, ?)",
            (guild_id, mod_id)
        )
        await self._execute(
            f"UPDATE mod_stats SET {col} = {col} + 1, updated_at = datetime('now') "
            f"WHERE guild_id = ? AND mod_id = ?",
            (guild_id, mod_id)
        )

    async def get_user_history(self, guild_id: int, user_id: int) -> List[Row]:
        return await self._fetchall("""
            SELECT * FROM mod_actions
            WHERE guild_id = ? AND user_id = ?
            ORDER BY created_at DESC
        """, (guild_id, user_id))

    async def get_mod_stats(self, guild_id: int, mod_id: int) -> Optional[Row]:
        return await self._fetchone(
            "SELECT * FROM mod_stats WHERE guild_id = ? AND mod_id = ?",
            (guild_id, mod_id)
        )

    async def get_guild_mod_stats(self, guild_id: int) -> List[Row]:
        """Топ-10 модераторов по суммарному числу действий."""
        return await self._fetchall("""
            SELECT *, (bans + kicks + mutes + warns) AS total
            FROM mod_stats
            WHERE guild_id = ?
            ORDER BY total DESC
            LIMIT 10
        """, (guild_id,))

    # ──────────────────────────────────────────
    # warnings — методы
    # ──────────────────────────────────────────

    async def add_warning(
        self, guild_id: int, user_id: int, mod_id: int, reason: str = None
    ) -> int:
        """Добавляет варн, возвращает текущее количество активных варнов."""
        await self._execute("""
            INSERT INTO warnings (guild_id, user_id, mod_id, reason)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, mod_id, reason))
        count = await self._fetchval("""
            SELECT COUNT(*) FROM warnings
            WHERE guild_id = ? AND user_id = ? AND active = 1
        """, (guild_id, user_id))
        return count

    async def get_active_warnings(self, guild_id: int, user_id: int) -> List[Row]:
        return await self._fetchall("""
            SELECT * FROM warnings
            WHERE guild_id = ? AND user_id = ? AND active = 1
            ORDER BY created_at
        """, (guild_id, user_id))

    async def clear_warnings(self, guild_id: int, user_id: int, mod_id: int):
        """Деактивирует все активные варны пользователя."""
        await self._execute("""
            UPDATE warnings SET active = 0
            WHERE guild_id = ? AND user_id = ? AND active = 1
        """, (guild_id, user_id))

    async def remove_warning(self, warning_id: int) -> bool:
        """Деактивирует конкретный варн по ID. Возвращает True если нашёл."""
        async with self.conn.execute(
            "UPDATE warnings SET active = 0 WHERE id = ? AND active = 1",
            (warning_id,)
        ) as cur:
            await self.conn.commit()
            return cur.rowcount > 0

    # ──────────────────────────────────────────
    # tickets — методы
    # ──────────────────────────────────────────

    async def create_ticket(
        self, guild_id: int, channel_id: int,
        user_id: int, subject: str = None
    ) -> int:
        """Создаёт тикет и возвращает его порядковый номер на сервере."""
        # Получаем следующий номер тикета для этого сервера
        num = await self._fetchval(
            "SELECT COALESCE(MAX(ticket_num), 0) + 1 FROM tickets WHERE guild_id = ?",
            (guild_id,)
        )
        await self._execute("""
            INSERT INTO tickets (guild_id, channel_id, user_id, ticket_num, subject)
            VALUES (?, ?, ?, ?, ?)
        """, (guild_id, channel_id, user_id, num, subject))
        return num

    async def get_ticket_by_channel(self, channel_id: int) -> Optional[Row]:
        return await self._fetchone(
            "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
        )

    async def close_ticket(self, channel_id: int, closed_by: int):
        await self._execute("""
            UPDATE tickets
            SET status = 'closed', closed_by = ?, closed_at = datetime('now')
            WHERE channel_id = ?
        """, (closed_by, channel_id))

    async def get_user_open_tickets(self, guild_id: int, user_id: int) -> int:
        """Количество открытых тикетов пользователя на сервере."""
        return await self._fetchval("""
            SELECT COUNT(*) FROM tickets
            WHERE guild_id = ? AND user_id = ? AND status = 'open'
        """, (guild_id, user_id))

    async def save_ticket_message(self, ticket_id: int, user_id: int, content: str):
        await self._execute("""
            INSERT INTO ticket_messages (ticket_id, user_id, content)
            VALUES (?, ?, ?)
        """, (ticket_id, user_id, content))

    async def get_ticket_messages(self, ticket_id: int) -> List[Row]:
        return await self._fetchall("""
            SELECT * FROM ticket_messages
            WHERE ticket_id = ? ORDER BY created_at
        """, (ticket_id,))

    # ──────────────────────────────────────────
    # banned_words — методы
    # ──────────────────────────────────────────

    async def add_banned_word(self, guild_id: int, word: str, mod_id: int):
        """Добавляет слово в фильтр. Дубликаты игнорируются."""
        await self._execute("""
            INSERT OR IGNORE INTO banned_words (guild_id, word, added_by)
            VALUES (?, ?, ?)
        """, (guild_id, word.lower(), mod_id))

    async def remove_banned_word(self, guild_id: int, word: str):
        await self._execute(
            "DELETE FROM banned_words WHERE guild_id = ? AND word = ?",
            (guild_id, word.lower())
        )

    async def get_banned_words(self, guild_id: int) -> List[str]:
        rows = await self._fetchall(
            "SELECT word FROM banned_words WHERE guild_id = ?", (guild_id,)
        )
        return [r["word"] for r in rows]

    # ──────────────────────────────────────────
    # automod_ignore — методы
    # ──────────────────────────────────────────

    async def is_channel_ignored(self, guild_id: int, channel_id: int) -> bool:
        """Проверяет, игнорируется ли канал автомодератором."""
        val = await self._fetchval(
            "SELECT 1 FROM automod_ignore WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id)
        )
        return val == 1

    async def add_ignored_channel(self, guild_id: int, channel_id: int):
        await self._execute(
            "INSERT OR IGNORE INTO automod_ignore (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id)
        )

    async def remove_ignored_channel(self, guild_id: int, channel_id: int):
        await self._execute(
            "DELETE FROM automod_ignore WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id)
        )
