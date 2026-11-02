"""Bounded request admission for one public API process; no visitor identifiers."""

import asyncio
from collections import deque
import math
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .bill_import import IMPORT_BODY_LIMIT

PAID_PATHS = frozenset({'/v1/agent/turn', '/v1/agent/continue', '/v1/agent/bill', '/v1/bills/import'})


class PublicAdmission:
    """Process-wide rolling windows, intentionally independent of forwarded headers."""

    def __init__(self, *, clock=monotonic, requests=60, sessions=6, paid=6,
                 concurrent=8, body_timeout=15):
        if any(type(value) is not int or value <= 0 for value in (requests, sessions, paid, concurrent)):
            raise ValueError('Admission limits must be positive integers')
        if not math.isfinite(body_timeout) or body_timeout <= 0:
            raise ValueError('Invalid body timeout')
        self._clock, self._concurrent = clock, concurrent
        self.body_timeout = body_timeout
        self._limits = {'all': requests, 'sessions': sessions, 'paid': paid}
        self._recent = {key: deque() for key in self._limits}
        self._active = 0
        self._lock = Lock()

    def enter(self, method, path):
        with self._lock:
            now = self._clock()
            for window in self._recent.values():
                while window and window[0] <= now - 60:
                    window.popleft()
            if self._active >= self._concurrent:
                raise HTTPException(429, 'Service busy; try again later', headers={'Retry-After': '1'})
            groups = ['all']
            if method == 'POST' and path == '/v1/sessions':
                groups.append('sessions')
            if method == 'POST' and path in PAID_PATHS:
                groups.append('paid')
            for group in groups:
                window = self._recent[group]
                if len(window) >= self._limits[group]:
                    retry = max(1, math.ceil(window[0] + 60 - now))
                    raise HTTPException(429, 'Request limit reached; try again later',
                                        headers={'Retry-After': str(retry)})
            for group in groups:
                self._recent[group].append(now)
            self._active += 1

    def leave(self):
        with self._lock:
            self._active -= 1


class PublicAdmissionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '').rstrip('/')
        policy = getattr(scope['app'].state, 'public_admission', None) if scope['type'] == 'http' else None
        if policy is None or not path.startswith('/v1/'):
            return await self.app(scope, receive, send)

        async def reject(status, detail, headers=None):
            await JSONResponse({'detail': detail}, status_code=status, headers=headers)(scope, receive, send)

        try:
            policy.enter(scope['method'], path)
        except HTTPException as error:
            return await reject(error.status_code, error.detail, error.headers)
        try:
            # Buffer once before routing, with actual-byte and whole-body time limits.
            # Existing endpoint parsers still enforce content type, consent and schema.
            limit = (IMPORT_BODY_LIMIT if path == '/v1/bills/import' else
                     16384 if path in PAID_PATHS else
                     12 * 1024 if path == '/v1/bills/compare' else
                     8192 if path == '/v1/anomaly/predict' else 1024)
            body = bytearray()
            try:
                async with asyncio.timeout(policy.body_timeout):
                    while True:
                        event = await receive()
                        if event['type'] == 'http.disconnect':
                            return
                        chunk = event.get('body', b'')
                        if len(body) + len(chunk) > limit:
                            return await reject(413, 'Request too large')
                        body.extend(chunk)
                        if not event.get('more_body', False):
                            break
            except TimeoutError:
                return await reject(408, 'Request body timed out')
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            policy.leave()
