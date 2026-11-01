"""Session-gated bill calculations; no uploads, model calls or persistence."""

from decimal import Decimal, InvalidOperation
import json

from fastapi import APIRouter, HTTPException, Request

from .bills import (BillComparison, BillComparisonRequest, ManualBill, NormalizedBill,
                    compare_bills, normalize_bill)
from .sessions import DemoSessions, require_session


class BillNormalizationResponse(NormalizedBill):
    request_id: str


class BillComparisonResponse(BillComparison):
    request_id: str


BILL_COMPARISON_BODY_LIMIT = 12 * 1024
# The response model registers ManualBill in OpenAPI components. Point the manually
# parsed request there too, rather than leaving a document-root #/$defs reference.
_COMPARISON_SCHEMA = BillComparisonRequest.model_json_schema(ref_template='#/components/schemas/{model}')
_COMPARISON_SCHEMA.pop('$defs', None)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-finite JSON number')


async def _read_bill_json(request: Request, limit: int):
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'Expected application/json')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > limit:
            raise HTTPException(413, 'Request too large')
        raw.extend(chunk)
    return json.loads(raw.decode('utf-8'), parse_float=Decimal,
                      parse_constant=_invalid_constant, object_pairs_hook=_unique_object)


def bill_router(sessions: DemoSessions) -> APIRouter:
    router = APIRouter()

    @router.post('/v1/bills/normalize', response_model=BillNormalizationResponse,
        openapi_extra={'requestBody': {'required': True, 'content': {
            'application/json': {'schema': ManualBill.model_json_schema()}}}})
    async def normalize(request: Request):
        store = require_session(sessions, request)
        _ = store.goal  # Check revocation even if it raced with the registry lookup.
        try:
            value = await _read_bill_json(request, 1024)
            bill = ManualBill.model_validate(value)
        except (ValueError, InvalidOperation, RecursionError):
            raise HTTPException(422, 'Invalid bill request') from None
        result = normalize_bill(bill)
        _ = store.goal  # Do not release bill data after expiry/revocation during the request.
        return BillNormalizationResponse(**result.model_dump(), request_id=request.state.request_id)

    @router.post('/v1/bills/compare', response_model=BillComparisonResponse,
        openapi_extra={'requestBody': {'required': True, 'content': {
            'application/json': {'schema': _COMPARISON_SCHEMA}}}})
    async def compare(request: Request):
        store = require_session(sessions, request)
        _ = store.goal
        try:
            value = await _read_bill_json(request, BILL_COMPARISON_BODY_LIMIT)
            entries = BillComparisonRequest.model_validate(value)
        except (ValueError, InvalidOperation, RecursionError):
            raise HTTPException(422, 'Invalid bill comparison request') from None
        _ = store.goal  # Do not calculate if the session ended while reading the body.
        result = compare_bills(entries)
        _ = store.goal  # Do not release bill data after expiry/revocation.
        return BillComparisonResponse(**result.model_dump(), request_id=request.state.request_id)

    return router
