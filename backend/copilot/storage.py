"""Local SQLite history and FTS5 retrieval. Raw audio/screenshots are not stored."""
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from .retrieval import fts_query, rank_documents


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT NOT NULL,updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
             role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
          CREATE VIRTUAL TABLE IF NOT EXISTS knowledge USING fts5(title,text,path UNINDEXED,tokenize='unicode61');
        ''')

    def new_session(self):
        session_id = str(uuid.uuid4())
        with self._lock, self.db:
            self.db.execute('INSERT INTO sessions VALUES (?,?,?)', (session_id, 'Новый диалог', self.now()))
        return session_id

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def exists(self, session_id):
        with self._lock:
            return self.db.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone() is not None

    def add_message(self, session_id, role, content):
        if role not in ('user', 'assistant'):
            raise ValueError('Недопустимая роль')
        if not self.exists(session_id):
            raise ValueError('Диалог не найден')
        stamp = self.now()
        with self._lock, self.db:
            self.db.execute('INSERT INTO messages(session_id,role,content,created_at) VALUES (?,?,?,?)',
                            (session_id, role, content, stamp))
            self.db.execute('UPDATE sessions SET updated_at=?,title=CASE WHEN title=? THEN ? ELSE title END WHERE id=?',
                            (stamp, 'Новый диалог', content[:70], session_id))

    def history(self, session_id, limit=100):
        with self._lock:
            rows = self.db.execute('SELECT role,content,created_at FROM (SELECT id,role,content,created_at FROM messages '
                                   'WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id',
                                   (session_id, max(1, min(int(limit), 500)))).fetchall()
            return [dict(row) for row in rows]

    def sessions(self):
        with self._lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 200')]

    def clear_history(self, session_id):
        with self._lock, self.db:
            self.db.execute('DELETE FROM messages WHERE session_id=?', (session_id,))
            self.db.execute('UPDATE sessions SET title=?,updated_at=? WHERE id=?', ('Новый диалог', self.now(), session_id))

    def import_knowledge(self, title, text, path):
        with self._lock, self.db:
            self.db.execute('DELETE FROM knowledge WHERE path=?', (path,))
            self.db.execute('INSERT INTO knowledge(title,text,path) VALUES (?,?,?)', (title[:200], text[:200000], path))

    def seed_knowledge(self, directory):
        for path in sorted(Path(directory).glob('*.md')):
            text = path.read_text(encoding='utf-8')
            title = text.splitlines()[0].lstrip('# ').strip()
            self.import_knowledge(title, text, 'bundled/' + path.name)

    def profile(self):
        """Pinned personal facts, independent of exact FTS word forms."""
        with self._lock:
            row = self.db.execute('SELECT title,text,path FROM knowledge WHERE path=?',
                                  ('user/profile.md',)).fetchone()
            return dict(row) if row else None

    def search(self, question, limit=4):
        match = fts_query(question[:1000])
        if not match:
            return []
        with self._lock:
            rows = self.db.execute('SELECT title,text,path,bm25(knowledge,4,1,0) AS score '
                                   'FROM knowledge WHERE knowledge MATCH ? ORDER BY score LIMIT 24',
                                   (match,)).fetchall()
            return rank_documents([dict(row) for row in rows], question, max(1, min(limit, 10)))

    def close(self):
        with self._lock:
            self.db.close()
