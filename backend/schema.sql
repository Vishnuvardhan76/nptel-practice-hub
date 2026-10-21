-- NPTEL Practice Hub Database Schema
-- Conservation Geography Assignment Questions & Practice Sessions

PRAGMA foreign_keys = ON;

-- Weeks metadata
CREATE TABLE IF NOT EXISTS weeks (
    week_number INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    total_questions INTEGER NOT NULL DEFAULT 0
);

-- Questions table: preserves original assignment order, question numbers, and verification status
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_number INTEGER NOT NULL,
    question_number INTEGER NOT NULL,       -- Original question number from assignment PDF
    question_order INTEGER NOT NULL,        -- Original sequential order in assignment PDF
    question_text TEXT NOT NULL,
    marks REAL NOT NULL DEFAULT 1.0,        -- Assignment marks when known, default 1.0
    is_verified INTEGER NOT NULL DEFAULT 0, -- 1 = verified bold answer; 0 = unverified / flagged
    flag_reason TEXT,                       -- Explicit rationale if manual verification is required
    FOREIGN KEY (week_number) REFERENCES weeks (week_number) ON DELETE CASCADE,
    UNIQUE (week_number, question_number)
);

-- Options table: preserves original option identifiers and sequence
CREATE TABLE IF NOT EXISTS options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    option_letter TEXT NOT NULL,            -- Original option letter ('a', 'b', 'c', 'd', etc.)
    option_order INTEGER NOT NULL,         -- Original display order (1, 2, 3, 4)
    option_text TEXT NOT NULL,
    is_correct INTEGER NOT NULL DEFAULT 0, -- 1 if verified bold in PDF; 0 otherwise
    FOREIGN KEY (question_id) REFERENCES questions (id) ON DELETE CASCADE,
    UNIQUE (question_id, option_letter),
    UNIQUE (question_id, option_order)
);

-- Server-side practice sessions: stores question and option order for active tests without exposing answer keys
CREATE TABLE IF NOT EXISTS practice_sessions (
    session_id TEXT PRIMARY KEY,            -- UUID string
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    selected_weeks TEXT NOT NULL,           -- JSON array of selected week numbers, e.g. [1, 2]
    test_type TEXT NOT NULL,                -- 'complete', 'quick_10', 'quick_20', 'quick_30', 'custom'
    question_ids TEXT NOT NULL,             -- JSON array of question IDs in shuffled sequence
    option_orders TEXT NOT NULL,            -- JSON object mapping question_id -> shuffled option_ids
    user_answers TEXT DEFAULT '{}',         -- JSON object mapping question_id -> option_id
    is_submitted INTEGER NOT NULL DEFAULT 0,
    submitted_at TIMESTAMP,
    score REAL DEFAULT 0.0,
    total_marks REAL DEFAULT 0.0,
    correct_count INTEGER DEFAULT 0,
    incorrect_count INTEGER DEFAULT 0,
    unanswered_count INTEGER DEFAULT 0,
    client_id TEXT
);
