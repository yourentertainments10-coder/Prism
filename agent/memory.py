"""
Provider-independent long-term memory persistence. Extracted from app.py —
behavior is unchanged.

If DATABASE_URL is set (e.g. a free Supabase Postgres project), memories are
stored there so they survive redeploys/restarts on hosts with an ephemeral
filesystem (like Render's free tier). Otherwise falls back to memories.json.
"""

import json
import os
import time

import psycopg2
from dotenv import dotenv_values, load_dotenv
from agent.timing import elapsed_ms, record

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_FILE = os.path.join(BASE_DIR, "memories.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

# Load the project configuration explicitly. Memory captures DATABASE_URL at
# import time, so path discovery can select another .env when Flask is launched
# from a different working directory. Prefer this project's value for memory,
# while leaving other environment variables' normal precedence unchanged.
load_dotenv(dotenv_path=ENV_FILE)
_dotenv_config = dotenv_values(ENV_FILE)

DATABASE_URL = (_dotenv_config.get("DATABASE_URL") or
                os.getenv("DATABASE_URL") or "")

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL:
        return
    started = time.perf_counter()
    record("memory_db_init_start", enabled=True)
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY, text TEXT NOT NULL, date TEXT NOT NULL)""")
            conn.commit()
        record("memory_db_init_end", enabled=True, duration_ms=elapsed_ms(started))
    except Exception as e:
        record("memory_db_init_error", enabled=False,
               error_type=type(e).__name__, duration_ms=elapsed_ms(started))
        print(f"[memory] DATABASE_URL set but init failed, memory will not persist: {e}")

def load_memories():
    started = time.perf_counter()
    record("memory_load_start")
    try:
        return _load_memories()
    finally:
        record("memory_load_end", duration_ms=elapsed_ms(started))


def _load_memories():
    if DATABASE_URL:
        try:
            with get_db() as conn, conn.cursor() as cur:
                cur.execute("SELECT text, date FROM memories ORDER BY id")
                return [{"text": t, "date": d} for t, d in cur.fetchall()]
        except Exception as e:
            record("memory_load_error", error_type=type(e).__name__)
            print(f"[memory] DB read failed: {e}")
            return []
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def add_memory(fact, date):
    if DATABASE_URL:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO memories (text, date) VALUES (%s, %s)", (fact, date))
            conn.commit()
        return
    mems = load_memories()
    mems.append({"text": fact, "date": date})
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mems, f, ensure_ascii=False, indent=1)
