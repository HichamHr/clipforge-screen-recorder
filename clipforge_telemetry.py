"""Optional, bounded local outbox. No media, paths, or logs are collected."""
import json
import sqlite3
import threading
import time
import urllib.request
import urllib.parse
import uuid
from contextlib import contextmanager
from pathlib import Path

EVENTS = {'app_opened', 'session_time', 'recording_started', 'recording_finished',
          'recording_failed', 'editor_opened', 'export_finished', 'export_failed'}
PROPERTIES = {'seconds', 'resolution', 'fps', 'audio', 'quality', 'operation', 'parts'}


class Telemetry:
    def __init__(self, directory, version, endpoint='', enabled=False):
        self.version, self.endpoint = version, endpoint.rstrip('/')
        self.enabled = enabled
        self.geo_enabled = False
        self.path = Path(directory) / 'outbox.sqlite3'
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.installation = None
        self.started = self.last_tick = time.monotonic()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    @property
    def configured(self):
        parsed = urllib.parse.urlsplit(self.endpoint)
        local_http = parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
        return ((parsed.scheme == 'https' or local_http) and bool(parsed.hostname) and
                not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        db.execute('CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, kind TEXT, body TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
        if self.installation is None:
            row = db.execute("SELECT value FROM metadata WHERE key='installation'").fetchone()
            self.installation = row[0] if row else str(uuid.uuid4())
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('installation', ?)", (self.installation,))
            db.commit()
        try:
            with db:
                yield db
        finally:
            db.close()

    def set_enabled(self, value):
        with self.lock:
            self.enabled = bool(value)
            self.last_tick = time.monotonic()
            try:
                with self.connect() as db:
                    if not self.enabled:
                        db.execute("DELETE FROM outbox WHERE kind='event'")
            except (OSError, sqlite3.Error):
                pass
        if self.enabled:
            self.track('app_opened')

    def enqueue(self, kind, data):
        if not self.configured:
            return False
        try:
            with self.lock, self.connect() as db:
                count = db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
                if count >= 500:
                    db.execute("DELETE FROM outbox WHERE id IN (SELECT id FROM outbox WHERE kind='event' ORDER BY rowid LIMIT 50)")
                    if db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0] >= 500:
                        return False
                identifier = str(uuid.uuid4())
                body = {'id': identifier, 'version': self.version, 'created_at': time.time(), **data}
                if kind == 'event':
                    body['installation'] = self.installation
                db.execute('INSERT INTO outbox VALUES (?, ?, ?)', (identifier, kind, json.dumps(body)))
            self.wake.set()
            return True
        except (OSError, sqlite3.Error):
            return False

    def track(self, name, **properties):
        with self.lock:
            if not self.enabled or name not in EVENTS:
                return False
            clean = {k: v for k, v in properties.items() if k in PROPERTIES and isinstance(v, (str, int, float, bool))}
            clean['geo_consent'] = self.geo_enabled
            return self.enqueue('event', {'name': name, 'properties': clean})

    def feedback(self, category, message, email=''):
        return self.enqueue('feedback', {'category': category, 'message': message, 'email': email})

    def flush(self):
        with self.lock:
            with self.connect() as db:
                rows = db.execute('SELECT id, kind, body FROM outbox ORDER BY rowid LIMIT 10').fetchall()
        for identifier, kind, body in rows:
            if self.stop.is_set():
                return
            if kind == 'event' and not self.enabled:
                with self.lock, self.connect() as db:
                    db.execute('DELETE FROM outbox WHERE id=?', (identifier,))
                continue
            if kind == 'event':
                payload = json.loads(body)
                payload['properties']['geo_consent'] = payload['properties'].get('geo_consent') is True and self.geo_enabled
                body = json.dumps(payload)
            request = urllib.request.Request(self.endpoint + '/v1/' + ('events' if kind == 'event' else 'feedback'),
                data=body.encode(), headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status not in (200, 201, 202):
                    return
            with self.lock:
                with self.connect() as db:
                    db.execute('DELETE FROM outbox WHERE id=?', (identifier,))

    def run(self):
        while not self.stop.is_set():
            self.wake.wait(60)
            self.wake.clear()
            if self.stop.is_set():
                break
            now = time.monotonic()
            if self.enabled and now-self.last_tick >= 60:
                self.track('session_time', seconds=round(now-self.last_tick))
                self.last_tick = now
            if self.configured:
                try:
                    self.flush()
                except Exception:
                    pass  # Offline/collector failure must never affect capture.

    def close(self):
        self.track('session_time', seconds=round(time.monotonic()-self.last_tick))
        self.stop.set()
        self.wake.set()
