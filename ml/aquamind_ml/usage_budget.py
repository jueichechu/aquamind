"""Durable paid-stage admission counter. Never stores request or visitor data."""

from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

from fastapi import HTTPException


class DailyStageBudget:
    def __init__(self, path: Path, limit: int, *, clock=lambda: datetime.now(timezone.utc).date()):
        if not path.is_absolute() or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Configure an absolute usage database path and a limit from 1 to 100')
        self.path, self.limit, self._clock = path, limit, clock
        try:
            with closing(sqlite3.connect(path, timeout=0)) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS daily_usage ('
                    'singleton INTEGER PRIMARY KEY CHECK(singleton = 1), day TEXT NOT NULL, '
                    'attempts INTEGER NOT NULL CHECK(attempts >= 0))')
                connection.commit()
        except sqlite3.Error:
            raise ValueError('Usage database unavailable') from None

    def reserve(self):
        """Commit before provider work. Failed/cancelled attempts are never refunded."""
        today = self._clock().isoformat()
        try:
            with closing(sqlite3.connect(self.path, timeout=0)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                row = connection.execute('SELECT day, attempts FROM daily_usage WHERE singleton=1').fetchone()
                used = 0
                if row is not None:
                    previous_day, previous_count = row
                    if (date.fromisoformat(previous_day).isoformat() != previous_day or
                            type(previous_count) is not int or previous_count < 0 or previous_day > today):
                        raise ValueError('Invalid usage state')
                    if previous_day == today:
                        used = previous_count
                if used >= self.limit:
                    raise HTTPException(429, 'Daily AI request limit reached', headers={'Retry-After': '86400'})
                connection.execute('INSERT INTO daily_usage(singleton, day, attempts) VALUES (1, ?, ?) '
                    'ON CONFLICT(singleton) DO UPDATE SET day=excluded.day, attempts=excluded.attempts',
                    (today, used + 1))
                connection.commit()
        except (sqlite3.Error, ValueError, TypeError):
            raise HTTPException(503, 'AI request budget unavailable') from None
