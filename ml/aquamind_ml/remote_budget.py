"""Durable AI-stage admission through Upstash REST; only a date/count is stored."""

import asyncio
from datetime import datetime, timezone
import json
import math
from urllib.parse import urlsplit

from fastapi import HTTPException

# One non-expiring hash keeps storage constant. Eviction must stay disabled.
RESERVE_STAGE_LUA = '''
local row = redis.call('HMGET', KEYS[1], 'day', 'attempts')
local today, limit = tonumber(ARGV[1]), tonumber(ARGV[2])
local used = 0
if row[1] or row[2] then
    if not row[1] or not row[2] then return -1 end
    if not string.match(row[1], '^%d+$') or not string.match(row[2], '^%d+$') then return -1 end
    local day, count = tonumber(row[1]), tonumber(row[2])
    if not day or day < 1 or day > 3652059 or not count or count > 100 or day > today then return -1 end
    if day == today then used = count end
end
if used >= limit then return 0 end
redis.call('HSET', KEYS[1], 'day', today, 'attempts', used + 1)
return 1
'''


class UpstashStageBudget:
    def __init__(self, client, url: str, token: str, limit: int, *,
                 clock=lambda: datetime.now(timezone.utc).date(), deadline=3):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.upstash.io') or
                parsed.username is not None or parsed.password is not None or parsed.port not in {None, 443} or
                parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            raise ValueError('Configure an official Upstash HTTPS REST URL')
        if not token or len(token) > 4096 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('Configure an Upstash REST token')
        if type(limit) is not int or not 1 <= limit <= 100 or not math.isfinite(deadline) or not 0 < deadline <= 3:
            raise ValueError('Invalid usage budget limits')
        self._client, self._url, self._token = client, url.rstrip('/'), token
        self.limit, self._clock, self._deadline = limit, clock, deadline

    async def reserve_async(self):
        command = ['EVAL', RESERVE_STAGE_LUA, 1, 'aquamind:paid-stages:v1',
                   self._clock().toordinal(), self.limit]
        try:
            async with asyncio.timeout(self._deadline):
                async with self._client.stream('POST', self._url, json=command,
                        headers={'Authorization': 'Bearer ' + self._token},
                        follow_redirects=False, timeout=2) as response:
                    if response.status_code != 200:
                        raise ValueError('Usage store rejected admission')
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > 4096:
                            raise ValueError('Invalid usage store response')
                        raw.extend(chunk)
                    body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {'result'} or type(body['result']) is not int:
                raise ValueError('Invalid usage store response')
            if body['result'] == 0:
                raise HTTPException(429, 'Daily AI request limit reached', headers={'Retry-After': '86400'})
            if body['result'] != 1:
                raise ValueError('Invalid usage state')
        except HTTPException:
            raise
        except Exception:
            # Unknown outcomes may have consumed quota. Never retry or start model work.
            raise HTTPException(503, 'AI request budget unavailable') from None
