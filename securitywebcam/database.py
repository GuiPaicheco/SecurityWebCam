from contextlib import contextmanager
import sqlite3
import time


class Database:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS recordings (
                  id TEXT PRIMARY KEY, root TEXT NOT NULL, name TEXT NOT NULL UNIQUE,
                  created REAL NOT NULL, mode TEXT NOT NULL, size INTEGER NOT NULL,
                  sha256 TEXT NOT NULL, duration REAL NOT NULL, preserved INTEGER DEFAULT 0,
                  local_state TEXT DEFAULT 'local', cloud_state TEXT DEFAULT 'not_selected',
                  cloud_root TEXT, cloud_name TEXT, attempts INTEGER DEFAULT 0,
                  retry_at REAL DEFAULT 0, cloud_error TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, at REAL NOT NULL, level TEXT, message TEXT);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def event(self, level, message):
        with self.connect() as db:
            db.execute('INSERT INTO events(at,level,message) VALUES(?,?,?)', (time.time(), level, message[:2000]))
            db.execute('DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-2000 FROM events)')
