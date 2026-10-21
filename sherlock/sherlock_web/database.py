"""SQLite database for search history and results."""

import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("SHERLOCK_DB_PATH", str(Path(__file__).parent / "sherlock_web.db"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_sites INTEGER DEFAULT 0,
            found_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL,
            site_name TEXT NOT NULL,
            url_main TEXT,
            url_user TEXT,
            status TEXT NOT NULL,
            http_status TEXT,
            response_time_ms REAL,
            FOREIGN KEY (search_id) REFERENCES searches(id)
        );
        CREATE INDEX IF NOT EXISTS idx_results_search_id ON results(search_id);
        CREATE INDEX IF NOT EXISTS idx_searches_username ON searches(username);
    """)
    conn.commit()
    conn.close()


def create_search(username: str) -> int:
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO searches (username, started_at) VALUES (?, ?)",
        (username, datetime.now(timezone.utc).isoformat()),
    )
    search_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return search_id


def add_result(search_id: int, site_name: str, url_main: str, url_user: str,
               status: str, http_status: str, response_time_ms: float):
    conn = get_db()
    conn.execute(
        """INSERT INTO results (search_id, site_name, url_main, url_user, status, http_status, response_time_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (search_id, site_name, url_main, url_user, status, http_status, response_time_ms),
    )
    conn.commit()
    conn.close()


def finish_search(search_id: int, total_sites: int, found_count: int, error_count: int):
    conn = get_db()
    conn.execute(
        """UPDATE searches SET finished_at=?, total_sites=?, found_count=?, error_count=?, status='completed'
           WHERE id=?""",
        (datetime.now(timezone.utc).isoformat(), total_sites, found_count, error_count, search_id),
    )
    conn.commit()
    conn.close()


def get_search_history(limit: int = 50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM searches ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_search_results(search_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM results WHERE search_id=? ORDER BY site_name", (search_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_search(search_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
