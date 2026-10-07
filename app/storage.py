import contextlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("CUOTI_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CuotiRecord" / "data"))).resolve()
DB_PATH = DATA_DIR / "library.db"
LOCK = threading.RLock()


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def decode(value, default=None):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


@contextlib.contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript('''
        CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY CHECK(id=1), nickname TEXT NOT NULL, grade TEXT NOT NULL, curriculum TEXT NOT NULL, semester TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, name TEXT NOT NULL, study_date TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'draft', sample INTEGER NOT NULL DEFAULT 0, warning TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE, name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE, number INTEGER NOT NULL, path TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '', UNIQUE(source_id,number));
        CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE, page_id TEXT REFERENCES pages(id) ON DELETE SET NULL, label TEXT NOT NULL, stem TEXT NOT NULL, work TEXT NOT NULL DEFAULT '', missing INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT 'wrong', selected INTEGER NOT NULL DEFAULT 1, saved INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, reflection TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS question_versions(id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE, version INTEGER NOT NULL, stem TEXT NOT NULL, work TEXT NOT NULL, missing INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(question_id,version));
        CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE, question_version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', answer TEXT NOT NULL DEFAULT '', correct_parts TEXT NOT NULL DEFAULT '', issues TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '', check_action TEXT NOT NULL DEFAULT '', causes TEXT NOT NULL DEFAULT '[]', knowledge_ids TEXT NOT NULL DEFAULT '[]', uncertainty TEXT NOT NULL DEFAULT '', model TEXT NOT NULL, prompt_version TEXT NOT NULL, knowledge_version TEXT NOT NULL, proposal TEXT NOT NULL, confirmed_at TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS analysis_changes(id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE, before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE, kind TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, current_index INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, completed_at TEXT, request_key TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, question_id TEXT REFERENCES questions(id) ON DELETE SET NULL, position INTEGER NOT NULL, snapshot TEXT NOT NULL, revealed INTEGER NOT NULL DEFAULT 0, hint_used INTEGER NOT NULL DEFAULT 0, UNIQUE(session_id,position));
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, item_id TEXT NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE, question_id TEXT REFERENCES questions(id) ON DELETE SET NULL, question_version INTEGER NOT NULL, result TEXT NOT NULL, hint_used INTEGER NOT NULL, completed_at TEXT NOT NULL);
        ''')
        db.execute("INSERT OR IGNORE INTO migrations VALUES(1,?)", (now(),))
        fields={r["name"] for r in db.execute("PRAGMA table_info(pages)")}
        for name in ("subject", "content_kind", "recognition_version"):
            if name not in fields:
                db.execute(f"ALTER TABLE pages ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        db.execute("INSERT OR IGNORE INTO migrations VALUES(2,?)", (now(),))
        if not db.execute('SELECT 1 FROM migrations WHERE version=3').fetchone():
            db.execute("UPDATE analyses SET status='stale' WHERE knowledge_version LIKE 'math-%'")
            db.execute("UPDATE sessions SET status='ended',completed_at=? WHERE status IN ('active','paused')",(now(),))
            db.execute("UPDATE profile SET curriculum='暂不确定' WHERE curriculum IN ('人教A版','人教B版')")
            db.execute('INSERT INTO migrations VALUES(3,?)',(now(),))
        if 'subject' not in {r['name'] for r in db.execute('PRAGMA table_info(sources)')}:
            db.execute("ALTER TABLE sources ADD COLUMN subject TEXT NOT NULL DEFAULT 'english'")
        if not db.execute('SELECT 1 FROM migrations WHERE version=4').fetchone():
            db.execute("UPDATE sources SET subject='math' WHERE name LIKE '%函数专题%' OR id IN (SELECT q.source_id FROM questions q JOIN analyses a ON a.question_id=q.id WHERE a.knowledge_version LIKE 'math-%')")
            db.execute('INSERT INTO migrations VALUES(4,?)',(now(),))
        db.execute("UPDATE tasks SET status='failed',message='服务已重启，可点击重试',error='任务中断',updated_at=? WHERE status IN ('queued','running')", (now(),))


def rows(query, args=()):
    with connect() as db:
        return [dict(r) for r in db.execute(query, args).fetchall()]


def one(query, args=()):
    result = rows(query, args)
    return result[0] if result else None


def execute(query, args=()):
    with connect() as db:
        return db.execute(query, args).rowcount


def task_update(task_id, status, message="", error=""):
    execute("UPDATE tasks SET status=?,message=?,error=?,updated_at=? WHERE id=?", (status, message, error, now(), task_id))
