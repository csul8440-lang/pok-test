-- ============================================================
-- migrations/001_init.sql — SQLite-схема базы данных
-- Используется только для справки: бот создаёт таблицы сам
-- через Database.init_tables() при первом запуске.
-- ============================================================

PRAGMA journal_mode=WAL;       -- режим WAL: лучшая конкурентность чтения/записи
PRAGMA foreign_keys=ON;        -- включаем поддержку внешних ключей

-- ────────────────────────────────────────
-- Конфигурация серверов Discord
-- Одна строка на каждый сервер
-- ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id        INTEGER PRIMARY KEY,

    prefix          TEXT    DEFAULT '!',
    lang            TEXT    DEFAULT 'ru',

    -- Каналы (ID Discord-каналов)
    log_channel     INTEGER,           -- общие логи сервера
    mod_log_channel INTEGER,           -- действия модераторов
    ticket_channel  INTEGER,           -- канал с кнопкой создания тикета
    ticket_category INTEGER,           -- категория для тикет-каналов

    -- Роли (ID Discord-ролей)
    mute_role       INTEGER,           -- резервная роль мута (не используется при timeout)
    mod_role        INTEGER,           -- роль модератора
    admin_role      INTEGER,           -- роль администратора
    ticket_support  INTEGER,           -- кто видит тикеты

    -- Переключатели систем (1=вкл, 0=выкл)
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
    automod_spam_limit       INTEGER DEFAULT 5,    -- сообщений за 5 сек = спам
    automod_caps_percent     INTEGER DEFAULT 70,   -- % заглавных букв для капс-фильтра
    automod_mention_limit    INTEGER DEFAULT 5,    -- макс. упоминаний в одном сообщении

    -- JSON-строка: сколько варнов → какое действие
    -- Пример: {"3":"mute_1h","5":"mute_24h","7":"kick","10":"ban"}
    warn_actions    TEXT    DEFAULT '{"3":"mute_1h","5":"mute_24h","7":"kick","10":"ban"}',

    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────
-- Запрещённые слова
-- ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS banned_words (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    word        TEXT    NOT NULL,
    added_by    INTEGER,                       -- ID модератора, добавившего слово
    added_at    TEXT    DEFAULT (datetime('now')),
    UNIQUE(guild_id, word)                     -- одно слово уникально на сервер
);

-- ────────────────────────────────────────
-- История всех действий модерации
-- ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mod_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,   -- кого наказали
    mod_id      INTEGER NOT NULL,   -- кто наказал (или ID бота для автомода)
    action      TEXT    NOT NULL,   -- ban / kick / mute / warn / unban / unmute
    reason      TEXT,               -- причина наказания
    duration    INTEGER,            -- длительность мута в секундах
    expires_at  TEXT,               -- ISO-8601, когда истекает наказание
    active      INTEGER DEFAULT 1,  -- 1=активно, 0=снято или истекло
    created_at  TEXT    DEFAULT (datetime('now'))
);
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
    active      INTEGER DEFAULT 1,  -- 1=активен, 0=снят модератором
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_warn_guild_user ON warnings(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_warn_active     ON warnings(guild_id, user_id, active);

-- ────────────────────────────────────────
-- Тикеты поддержки
-- ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL UNIQUE,   -- ID Discord-канала тикета
    user_id     INTEGER NOT NULL,           -- создатель тикета
    ticket_num  INTEGER NOT NULL,           -- порядковый номер на сервере
    subject     TEXT,                       -- тема обращения
    status      TEXT    DEFAULT 'open',     -- open / closed / deleted
    closed_by   INTEGER,                    -- кто закрыл
    created_at  TEXT    DEFAULT (datetime('now')),
    closed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ticket_guild  ON tickets(guild_id);
CREATE INDEX IF NOT EXISTS idx_ticket_user   ON tickets(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_ticket_status ON tickets(guild_id, status);

-- ────────────────────────────────────────
-- Сообщения тикетов (для транскриптов)
-- ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ticket_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    content     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ────────────────────────────────────────
-- Статистика модераторов
-- Одна строка на пару (сервер, модератор)
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
    PRIMARY KEY (guild_id, mod_id)
);

-- ────────────────────────────────────────
-- Белый список разрешённых доменов
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
