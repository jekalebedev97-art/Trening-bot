import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

class Database:
    def __init__(self):
        self.url = os.environ["DATABASE_URL"]
        self._init()

    def _conn(self):
        return psycopg2.connect(self.url, cursor_factory=RealDictCursor)

    def _init(self):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id BIGINT PRIMARY KEY,
                        name TEXT,
                        created_at DATE DEFAULT CURRENT_DATE
                    );
                    CREATE TABLE IF NOT EXISTS workouts (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        date TEXT,
                        exercise TEXT,
                        sets INTEGER,
                        reps INTEGER,
                        weight REAL,
                        note TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS weights (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        date TEXT,
                        value REAL
                    );
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        role TEXT,
                        content TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS profiles (
                        user_id BIGINT PRIMARY KEY,
                        content TEXT
                    );
                """)
            conn.commit()

    def ensure_user(self, user_id: int, name: str):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (user_id, name)
                )
            conn.commit()

    # ── PROFILE ───────────────────────────────────────────────────────────────
    def get_profile(self, user_id: int) -> str:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT content FROM profiles WHERE user_id=%s", (user_id,))
                row = cur.fetchone()
        return row["content"] if row else None

    def save_profile(self, user_id: int, content: str):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO profiles (user_id, content) VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET content=EXCLUDED.content
                """, (user_id, content))
            conn.commit()

    # ── WORKOUTS ──────────────────────────────────────────────────────────────
    def add_workout(self, user_id, date, exercise, sets, reps, weight, note=""):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO workouts (user_id,date,exercise,sets,reps,weight,note) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (user_id, date, exercise, sets, reps, weight, note)
                )
            conn.commit()

    def get_workouts(self, user_id, limit=50):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM workouts WHERE user_id=%s ORDER BY date DESC, id DESC LIMIT %s",
                    (user_id, limit)
                )
                return [dict(r) for r in cur.fetchall()]

    def get_workouts_count(self, user_id):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(DISTINCT date) as cnt FROM workouts WHERE user_id=%s",
                    (user_id,)
                )
                row = cur.fetchone()
        return row["cnt"] if row else 0

    def get_progression_analysis(self, user_id):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT exercise,date,sets,reps,weight,note FROM workouts WHERE user_id=%s ORDER BY exercise,date",
                    (user_id,)
                )
                rows = cur.fetchall()
        result = {}
        for r in rows:
            ex = r["exercise"]
            if ex not in result:
                result[ex] = []
            result[ex].append(dict(r))
        return result

    # ── WEIGHTS ───────────────────────────────────────────────────────────────
    def add_weight(self, user_id, date, value):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO weights (user_id,date,value) VALUES (%s,%s,%s)",
                    (user_id, date, value)
                )
            conn.commit()

    def get_weights(self, user_id, limit=20):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM weights WHERE user_id=%s ORDER BY date DESC LIMIT %s",
                    (user_id, limit)
                )
                return [dict(r) for r in cur.fetchall()]

    # ── CHAT HISTORY ──────────────────────────────────────────────────────────
    def add_chat_message(self, user_id, role, content):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_history (user_id,role,content) VALUES (%s,%s,%s)",
                    (user_id, role, content)
                )
                cur.execute("""
                    DELETE FROM chat_history WHERE user_id=%s AND id NOT IN (
                        SELECT id FROM chat_history WHERE user_id=%s ORDER BY id DESC LIMIT 60
                    )
                """, (user_id, user_id))
            conn.commit()

    def get_chat_history(self, user_id, limit=20):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT role,content FROM chat_history WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                    (user_id, limit)
                )
                rows = cur.fetchall()
        return [dict(r) for r in reversed(rows)]
