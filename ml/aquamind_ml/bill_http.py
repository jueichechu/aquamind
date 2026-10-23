"""Session-gated, stateless bill normalization; no uploads, model calls or persistence."""

from decimal import Decimal, InvalidOperation
import json

from fastapi import APIRouter, HTTPException, Request

from .bills import ManualBill, NormalizedBill, normalize_bill
from .sessions import DemoSessions, require_session


class BillNormalizationResponse(NormalizedBill):
    request_id: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-finite JSON number')


def bill_router(sessions: DemoSessions) -> APIRouter:
    router = APIRouter()

    @router.post('/v1/bills/normalize', response_model=BillNormalizationResponse,
        openapi_extra={'requestBody': {'required': True, 'content': {
            'application/json': {'schema': ManualBill.model_json_schema()}}}})
    async def normalize(request: Request):
        store = require_session(sessions, request)
        _ = store.goal  # Check revocation even if it raced with the registry lookup.
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Expected application/json')
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 1024:
                raise HTTPException(413, 'Request too large')
            raw.extend(chunk)
        try:
            value = json.loads(raw.decode('utf-8'), parse_float=Decimal,
                               parse_constant=_invalid_constant, object_pairs_hook=_unique_object)
            bill = ManualBill.model_validate(value)
        except (ValueError, InvalidOperation, RecursionError):
            raise HTTPException(422, 'Invalid bill request') from None
        result = normalize_bill(bill)
        _ = store.goal  # Do not release bill data after expiry/revocation during the request.
        return BillNormalizationResponse(**result.model_dump(), request_id=request.state.request_id)

    return router
