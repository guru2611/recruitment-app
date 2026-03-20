import sqlite3
import logging
from pathlib import Path
from config import DB_PATH

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS job_descriptions (
                jd_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                folder_path TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cv_path      TEXT NOT NULL UNIQUE,
                name         TEXT,
                phone        TEXT,
                email        TEXT,
                status       TEXT DEFAULT 'pending',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS matches (
                match_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES candidates(candidate_id),
                jd_id        INTEGER NOT NULL REFERENCES job_descriptions(jd_id),
                match_score  INTEGER NOT NULL,
                matched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(candidate_id, jd_id)
            );

            CREATE TABLE IF NOT EXISTS communications (
                comm_id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id      INTEGER NOT NULL UNIQUE REFERENCES candidates(candidate_id),
                whatsapp_sent     BOOLEAN DEFAULT 0,
                whatsapp_sent_at  TIMESTAMP,
                call_made         BOOLEAN DEFAULT 0,
                call_made_at      TIMESTAMP,
                invite_sent       BOOLEAN DEFAULT 0,
                invite_sent_at    TIMESTAMP
            );
        """)
    logger.info("Database initialised at %s", DB_PATH)
