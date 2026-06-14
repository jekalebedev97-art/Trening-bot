import sqlite3
from datetime import datetime
from typing import Optional

class Database:
    def __init__(self, path: str):
        self.path = path
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    created_at TEXT DEFAULT (date('now'))
                );

                CREATE TABLE IF NOT EXISTS workouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    date TEXT,
                    exercise TEXT,
                    sets INTEGER,
                    reps INTEGER,
                    weight REAL,
                    note TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS weights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    date TEXT,
                    value REAL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
            """)

    def ensure_user(self, user_id: int, name: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, name) VALUES (?, ?)",
                (user_id, name)
            )

    # ── WORKOUTS ──────────────────────────────────────────────────────────────
    def add_workout(self, user_id: int, date: str, exercise: str,
                    sets: int, reps: int, weight: float, note: str = ""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO workouts (user_id, date, exercise, sets, reps, weight, note) VALUES (?,?,?,?,?,?,?)",
                (user_id, date, exercise, sets, reps, weight, note)
            )

    def get_workouts(self, user_id: int, limit: int = 50) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workouts WHERE user_id=? ORDER BY date DESC, id DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_workouts_count(self, user_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT date) as cnt FROM workouts WHERE user_id=?",
                (user_id,)
            ).fetchone()
        return row["cnt"] if row else 0

    def get_progression_analysis(self, user_id: int) -> dict:
        """Возвращает словарь {упражнение: [{date, sets, reps, weight}]} для анализа прогрессии"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT exercise, date, sets, reps, weight
                   FROM workouts WHERE user_id=?
                   ORDER BY exercise, date""",
                (user_id,)
            ).fetchall()

        result = {}
        for r in rows:
            ex = r["exercise"]
            if ex not in result:
                result[ex] = []
            result[ex].append({
                "date": r["date"],
                "sets": r["sets"],
                "reps": r["reps"],
                "weight": r["weight"]
            })
        return result

    # ── WEIGHTS ───────────────────────────────────────────────────────────────
    def add_weight(self, user_id: int, date: str, value: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO weights (user_id, date, value) VALUES (?,?,?)",
                (user_id, date, value)
            )

    def get_weights(self, user_id: int, limit: int = 20) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM weights WHERE user_id=? ORDER BY date DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── CHAT HISTORY ──────────────────────────────────────────────────────────
    def add_chat_message(self, user_id: int, role: str, content: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)",
                (user_id, role, content)
            )
            # Оставляем только последние 60 сообщений
            conn.execute("""
                DELETE FROM chat_history
                WHERE user_id=? AND id NOT IN (
                    SELECT id FROM chat_history WHERE user_id=?
                    ORDER BY id DESC LIMIT 60
                )
            """, (user_id, user_id))

    def get_chat_history(self, user_id: int, limit: int = 20) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
