import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, csrf TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    request_id TEXT NOT NULL, text TEXT NOT NULL, revision INTEGER NOT NULL,
    response TEXT, created REAL NOT NULL, UNIQUE(session_id, request_id)
);
CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, service TEXT NOT NULL, slot TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','cancelled')), version INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS active_slot ON bookings(slot) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), owner TEXT NOT NULL,
    revision INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
    expected_version INTEGER, status TEXT NOT NULL CHECK(status IN
      ('draft','waiting_confirmation','executing','committed','failed','cancelled')),
    confirmation TEXT NOT NULL, expires REAL NOT NULL, confirmed REAL,
    receipt TEXT, reason TEXT, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), operation_id TEXT,
    kind TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL
);
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(transaction=False) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, write=False, transaction=True):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            if transaction:
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            if transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()
