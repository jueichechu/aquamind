"""Opt-in, session-isolated meter imports; no provider calls or persistence."""

from decimal import InvalidOperation

from fastapi import APIRouter, HTTPException, Request

from .bill_http import _read_bill_json
from .meter_import import METER_BODY_LIMIT, MeterCsvError, MeterImportRequest, parse_meter_csv
from .meter_session import ImportedMeterSummary
from .sessions import DemoSessions, session_token


def meter_router(sessions: DemoSessions) -> APIRouter:
    router = APIRouter()

    def store_for(request):
        if not request.app.state.meter_import_enabled:
            raise HTTPException(404, 'Meter import unavailable')
        try:
            store = sessions.meters(session_token(request))
        except LookupError:
            raise HTTPException(401, 'Session unavailable') from None
        store.current()  # Recheck cached-reference revocation before reading a body.
        return store

    @router.post('/v1/meters/import', response_model=ImportedMeterSummary, status_code=201,
        openapi_extra={'requestBody': {'required': True, 'content': {
            'application/json': {'schema': MeterImportRequest.model_json_schema()}}}})
    async def import_meter(request: Request):
        store = store_for(request)
        try:
            value = await _read_bill_json(request, METER_BODY_LIMIT)
            body = MeterImportRequest.model_validate(value)
            dataset = parse_meter_csv(body)
        except MeterCsvError as error:
            raise HTTPException(422, str(error)) from None
        except (ValueError, InvalidOperation, RecursionError):
            raise HTTPException(422, 'Invalid meter import request') from None
        return store.replace(dataset)

    @router.get('/v1/meters/current', response_model=ImportedMeterSummary | None)
    def current_meter(request: Request):
        return store_for(request).current()

    @router.delete('/v1/meters/current', status_code=204)
    def clear_meter(request: Request):
        store_for(request).clear()

    return router
