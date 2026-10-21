"""ClipForge collector. Deploy behind HTTPS with a persistent data volume."""
import os
import sqlite3
import time
from pathlib import Path
from typing import Literal
from uuid import UUID
from contextlib import contextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@contextmanager
def database():
    path = Path(os.environ.get('CLIPFORGE_DB', 'data/collector.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.execute('CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, kind TEXT, received REAL, body TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS submissions_kind ON submissions(kind)')
    try:
        with db:
            yield db
    finally:
        db.close()


class BaseSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: UUID
    version: str = Field(min_length=1, max_length=30)
    created_at: float = Field(ge=0)


class Properties(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    seconds: int | None = Field(default=None, ge=0, le=31536000)
    resolution: str | None = Field(default=None, max_length=30)
    fps: int | None = Field(default=None, ge=1, le=240)
    audio: str | None = Field(default=None, max_length=40)
    quality: str | None = Field(default=None, max_length=30)
    operation: Literal['trim', 'crop', 'split'] | None = None
    parts: int | None = Field(default=None, ge=1, le=100)


class Event(BaseSubmission):
    installation: UUID
    name: Literal['app_opened', 'session_time', 'recording_started', 'recording_finished',
                  'recording_failed', 'editor_opened', 'export_finished', 'export_failed']
    properties: Properties


class Feedback(BaseSubmission):
    category: Literal['Suggestion', 'Bug', 'Other']
    message: str = Field(min_length=1, max_length=4000)
    email: str = Field(default='', max_length=254)


@app.middleware('http')
async def bound_request(request: Request, call_next):
    # Enforce before parsing, including chunked requests. No IPs are stored here.
    from starlette.responses import JSONResponse
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 24000:
            return JSONResponse({'detail': 'Request too large'}, status_code=413)
    request._body = bytes(body)
    return await call_next(request)


def store(kind, submission):
    with database() as db:
        db.execute('INSERT OR IGNORE INTO submissions VALUES (?, ?, ?, ?)',
                   (str(submission.id), kind, time.time(), submission.model_dump_json()))
    return {'accepted': True, 'id': str(submission.id)}


@app.post('/v1/events', status_code=202)
def event(data: Event):
    return store('event', data)


@app.post('/v1/feedback', status_code=202)
def feedback(data: Feedback):
    return store('feedback', data)


@app.get('/health')
def health():
    return {'status': 'ok'}
