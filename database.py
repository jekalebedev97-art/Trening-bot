import os
import pg8000.native
from urllib.parse import urlparse

class Database:
    def __init__(self):
        self.url = os.environ["DATABASE_URL"]
        self._init()

    def _conn(self):
        u = urlparse(self.url)
        return pg8000.native.Connection(
            host=u.hostname,
            port=u.port or 5432,
            database=u.path.lstrip("/"),
            user=u.username,
            password=u.password,
            ssl_context=True
        )

    def _init(self):
        conn = self._conn()
        conn.run("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                name TEXT,
                created_at DATE DEFAULT CURRENT_DATE
            )
        """)
        conn.run("""
            CREATE TABLE IF NOT EXISTS workouts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                date TEXT,
                exercise TEXT,
                sets INTEGER,
                reps INTEGER,
                weight REAL,
                note TEXT DEFAULT ''
            )
        """)
        conn.run("""
            CREATE TABLE IF NOT EXISTS weights (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                date TEXT,
                value REAL
            )
        """)
        conn.run("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
                content TEXT
            )
        """)
        conn.run("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                role TEXT,
                content TEXT
            )
        """)
        conn.close()

    def ensure_user(self, user_id: int, name: str):
        conn = self._conn()
        conn.run(
            "INSERT INTO users (id, name) VALUES (:id, :name) ON CONFLICT (id) DO NOTHING",
            id=user_id, name=name
        )
        conn.close()

    def get_profile(self, user_id: int):
        conn = self._conn()
        rows = conn.run("SELECT content FROM profiles WHERE user_id=:uid", uid=user_id)
        conn.close()
        return rows[0][0] if rows else None

    def save_profile(self, user_id: int, content: str):
        conn = self._conn()
        conn.run("""
            INSERT INTO profiles (user_id, content) VALUES (:uid, :content)
            ON CONFLICT (user_id) DO UPDATE SET content=EXCLUDED.content
        """, uid=user_id, content=content)
        conn.close()

    def add_workout(self, user_id, date, exercise, sets, reps, weight, note=""):
        conn = self._conn()
        conn.run(
            "INSERT INTO workouts (user_id,date,exercise,sets,reps,weight,note) VALUES (:u,:d,:e,:s,:r,:w,:n)",
            u=user_id, d=date, e=exercise, s=sets, r=reps, w=weight, n=note
        )
        conn.close()

    def get_workouts(self, user_id, limit=50):
        conn = self._conn()
        rows = conn.run(
            "SELECT id,user_id,date,exercise,sets,reps,weight,note FROM workouts WHERE user_id=:u ORDER BY date DESC, id DESC LIMIT :l",
            u=user_id, l=limit
        )
        conn.close()
        keys = ["id","user_id","date","exercise","sets","reps","weight","note"]
        return [dict(zip(keys, r)) for r in rows]

    def get_workouts_count(self, user_id):
        conn = self._conn()
        rows = conn.run("SELECT COUNT(DISTINCT date) FROM workouts WHERE user_id=:u", u=user_id)
        conn.close()
        return rows[0][0] if rows else 0

    def get_progression_analysis(self, user_id):
        conn = self._conn()
        rows = conn.run(
            "SELECT exercise,date,sets,reps,weight,note FROM workouts WHERE user_id=:u ORDER BY exercise,date",
            u=user_id
        )
        conn.close()
        keys = ["exercise","date","sets","reps","weight","note"]
        result = {}
        for r in rows:
            d = dict(zip(keys, r))
            ex = d["exercise"]
            if ex not in result:
                result[ex] = []
            result[ex].append(d)
        return result

    def add_weight(self, user_id, date, value):
        conn = self._conn()
        conn.run("INSERT INTO weights (user_id,date,value) VALUES (:u,:d,:v)", u=user_id, d=date, v=value)
        conn.close()

    def get_weights(self, user_id, limit=20):
        conn = self._conn()
        rows = conn.run(
            "SELECT id,user_id,date,value FROM weights WHERE user_id=:u ORDER BY date DESC LIMIT :l",
            u=user_id, l=limit
        )
        conn.close()
        keys = ["id","user_id","date","value"]
        return [dict(zip(keys, r)) for r in rows]

    def add_chat_message(self, user_id, role, content):
        conn = self._conn()
        conn.run(
            "INSERT INTO chat_history (user_id,role,content) VALUES (:u,:r,:c)",
            u=user_id, r=role, c=content
        )
        rows = conn.run("SELECT id FROM chat_history WHERE user_id=:u ORDER BY id DESC LIMIT 60", u=user_id)
        if rows:
            min_id = rows[-1][0]
            conn.run("DELETE FROM chat_history WHERE user_id=:u AND id < :mid", u=user_id, mid=min_id)
        conn.close()

    def get_chat_history(self, user_id, limit=20):
        conn = self._conn()
        rows = conn.run(
            "SELECT role,content FROM chat_history WHERE user_id=:u ORDER BY id DESC LIMIT :l",
            u=user_id, l=limit
        )
        conn.close()
        keys = ["role","content"]
        return [dict(zip(keys, r)) for r in reversed(rows)]
