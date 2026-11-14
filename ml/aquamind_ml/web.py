"""Serve exported website files and the existing allowlisted API in one process.

This is the public hosting adapter. The underlying API keeps its own relay,
session, admission, consent and approval controls. No raw API routes are mounted.
"""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
import httpx
from starlette.staticfiles import StaticFiles

from .api import create_app
from .bill_import import IMPORT_BODY_LIMIT
from .meter_import import METER_BODY_LIMIT
from .voice import AUDIO_BODY_LIMIT


SAFE_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
ALLOWED = frozenset({
    ('GET', 'v1/bills/readiness'), ('POST', 'v1/sessions'), ('DELETE', 'v1/session'),
    ('GET', 'v1/goals/current'), ('POST', 'v1/goals/proposals'),
    ('POST', 'v1/agent/turn'), ('POST', 'v1/agent/continue'), ('POST', 'v1/agent/bill'),
    ('POST', 'v1/agent/evidence'),
    ('POST', 'v1/audio/transcribe'),
    ('POST', 'v1/bills/normalize'), ('POST', 'v1/bills/import'), ('POST', 'v1/bills/compare'),
    ('POST', 'v1/meters/import'), ('GET', 'v1/meters/current'), ('DELETE', 'v1/meters/current'),
})
PAGES = {'': 'index.html', 'analyze': 'analyze.html', 'compare': 'compare.html', 'demo': 'demo.html', 'meter': 'meter.html'}
BODY_SECONDS = 15


class WebsiteFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Known extensionless routes retain their existing URLs. StaticFiles
        # resolves all other assets and rejects traversal/symlinks outside root.
        response = await super().get_response(PAGES.get(path.rstrip('/'), path), scope)
        # Do not let a fresh browser navigation reuse HTML before this process
        # has completed startup. Versioned build assets can be cached normally.
        response.headers['Cache-Control'] = ('public, max-age=31536000, immutable'
            if path.startswith('_next/static/') else 'no-store')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response


def failure(detail, status, headers=None):
    return JSONResponse({'detail': detail}, status_code=status,
                        headers=SAFE_HEADERS | (headers or {}))


def relay_headers(env):
    mode = env.get('AQUAMIND_RELAY_REQUIRED', '0')
    secret = env.get('AQUAMIND_RELAY_SECRET', '')
    if mode not in {'0', '1'} or (mode == '1' and not re.fullmatch(r'[\x21-\x7e]{32,128}', secret)):
        raise ValueError('Invalid relay configuration')
    if env.get('AQUAMIND_PUBLIC_MODE', '0') not in {'0', '1'}:
        raise ValueError('Invalid public configuration')
    return {'X-AquaMind-Relay-Key': secret} if mode == '1' else {}


def allowed(method, path):
    return ((method, path) in ALLOWED or
        (method == 'GET' and re.fullmatch(r'v1/approvals/[0-9a-f-]{36}', path)) or
        (method == 'POST' and re.fullmatch(r'v1/approvals/[0-9a-f-]{36}/decision', path)))


def readiness_response(upstream, headers):
    try:
        if len(upstream.content) > 1024 or upstream.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise ValueError('Invalid readiness response')
        value = upstream.json()
        if not isinstance(value, dict):
            raise ValueError('Invalid readiness response')
        ready = upstream.status_code == 200 and value == {'status': 'ready'}
        error = (400 <= upstream.status_code <= 599 and
            isinstance(value.get('detail'), str) and len(value['detail']) <= 160 and
            set(value) <= {'detail', 'request_id'} and
            ('request_id' not in value or (isinstance(value['request_id'], str) and
                re.fullmatch(r'[0-9a-f-]{36}', value['request_id']))))
        if not ready and not error:
            raise ValueError('Invalid readiness response')
        return Response(upstream.content, status_code=upstream.status_code, headers=headers)
    except (ValueError, TypeError):
        return failure('Bill analysis unavailable', 503, headers)


def create_web_app(static_dir=None, *, api=None):
    api = create_app() if api is None else api
    directory = Path(static_dir) if static_dir is not None else Path(__file__).resolve().parents[2] / 'apps/web/out'
    active = 0

    @asynccontextmanager
    async def lifespan(app):
        if not all((directory / name).is_file() for name in PAGES.values()):
            raise RuntimeError('Website export unavailable')
        headers = relay_headers(os.environ)
        async with api.router.lifespan_context(api):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api),
                    base_url='http://aquamind.internal', follow_redirects=False) as client:
                probes = [('/health', 'ok')]
                if os.environ.get('AQUAMIND_INFERENCE_ENABLED', '1') == '1':
                    probes.append(('/ready', 'ready'))
                if os.environ.get('AQUAMIND_AGENT_ENABLED') == '1':
                    probes.append(('/v1/bills/readiness', 'ready'))
                for path, expected in probes:
                    response = await client.get(path, headers=headers)
                    if response.status_code != 200 or response.json().get('status') != expected:
                        raise RuntimeError('Website backend startup unavailable')
                app.state.backend = client
                # Uvicorn does not open the public listener until lifespan yields.
                yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/api/health')
    async def health():
        try:
            async with asyncio.timeout(5):
                response = await app.state.backend.get('/health')
            if response.status_code == 200 and response.json().get('status') == 'ok':
                return JSONResponse({'status': 'ok'}, headers=SAFE_HEADERS)
        except Exception:
            pass
        return JSONResponse({'status': 'unavailable'}, status_code=503, headers=SAFE_HEADERS)

    @app.api_route('/api/aquamind/{path:path}', methods=['GET', 'POST', 'DELETE'])
    async def relay(path: str, request: Request):
        nonlocal active
        try:
            headers = {'Content-Type': 'application/json'} | relay_headers(os.environ)
        except ValueError:
            return failure('Demo backend unavailable', 503)
        limited = os.environ.get('AQUAMIND_PUBLIC_MODE', '0') == '1'
        if limited and active >= 8:
            return failure('Service busy; try again later', 429, {'Retry-After': '1'})
        if limited:
            active += 1
        importing = path == 'v1/bills/import'
        transcribing = path == 'v1/audio/transcribe'
        readiness = path == 'v1/bills/readiness'
        new_turn = path in {'v1/agent/turn', 'v1/agent/bill', 'v1/agent/evidence'}
        agent = new_turn or path == 'v1/agent/continue' or importing or transcribing
        try:
            if not allowed(request.method, path):
                return failure('Unknown endpoint', 404)
            limit = (IMPORT_BODY_LIMIT if importing else AUDIO_BODY_LIMIT if transcribing else METER_BODY_LIMIT if path == 'v1/meters/import'
                else 16384 if new_turn else 12 * 1024 if path == 'v1/bills/compare' else 1024)
            body = bytearray()
            if request.method == 'POST':
                try:
                    async with asyncio.timeout(BODY_SECONDS):
                        async for chunk in request.stream():
                            if len(body) + len(chunk) > limit:
                                return failure('Request too large', 413)
                            body.extend(chunk)
                except TimeoutError:
                    return failure('Request body timed out', 408)
            authorization = ', '.join(request.headers.getlist('authorization'))
            if authorization:
                headers['Authorization'] = authorization
            # ASGI transport never performs network I/O or retries. Host-owned
            # headers replace browser relay keys; cookies/forwarded headers stay out.
            async with asyncio.timeout(70 if readiness else 135 if agent else 10):
                upstream = await app.state.backend.request(request.method, '/' + path,
                    content=bytes(body) if request.method == 'POST' else None, headers=headers)
            response_headers = {'Content-Type': 'application/json'} | SAFE_HEADERS
            retry = upstream.headers.get('retry-after', '')
            if (upstream.status_code == 429 or (readiness and upstream.status_code == 503)) and re.fullmatch(r'[1-9][0-9]{0,5}', retry):
                response_headers['Retry-After'] = retry
            if readiness:
                return readiness_response(upstream, response_headers)
            return Response(None if upstream.status_code == 204 else upstream.content,
                            status_code=upstream.status_code, headers=response_headers)
        except Exception:
            return failure('Agent request could not be confirmed' if agent else 'Demo backend unavailable', 503)
        finally:
            if limited:
                active -= 1

    app.mount('/', WebsiteFiles(directory=directory, html=True, check_dir=False))
    return app


app = create_web_app()
