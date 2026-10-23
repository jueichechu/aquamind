"""Local FastAPI serving for the frozen daily-window leak detector."""

from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
import torch

from .data import MeterWindow
from .detector import FrozenDetector
from .sessions import DemoSessions, approval_router
from .approvals import ApprovalSessionUnavailable
from .bill_http import bill_router

logger = logging.getLogger("aquamind.api")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)
logger.propagate = False
Flow = Annotated[float, Field(strict=True, ge=0, le=1000, allow_inf_nan=False)]


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_timestamp: str = Field(max_length=40)
    flow_rates_gpm: list[Flow] = Field(min_length=96, max_length=96)

    @field_validator("start_timestamp")
    @classmethod
    def midnight_utc(cls, value):
        start = datetime.fromisoformat(value)
        if (start.utcoffset() != timedelta(0) or
                (start.hour, start.minute, start.second, start.microsecond) != (0, 0, 0, 0)):
            raise ValueError("Expected midnight UTC")
        # Ensure the final interval timestamp is representable.
        try:
            start + timedelta(minutes=95 * 15)
        except OverflowError:
            raise ValueError("Timestamp outside supported range") from None
        return start.isoformat()


class PredictionResponse(BaseModel):
    score: float = Field(ge=0, allow_inf_nan=False)
    is_leak: bool
    threshold: float
    model_version: str
    request_id: str
    training_data: Literal["synthetic"] = "synthetic"
    unit: Literal["daily_window"] = "daily_window"


def create_app(detector_path: Path | None = None, *, sessions: DemoSessions | None = None,
               agent_host=None) -> FastAPI:
    lock = Lock()

    @asynccontextmanager
    async def lifespan(app):
        previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        app.state.detector = None
        try:
            configured = detector_path or os.environ.get("AQUAMIND_DETECTOR_PATH")
            if configured:
                try:
                    app.state.detector = FrozenDetector(Path(configured))
                except Exception as error:
                    logger.error(json.dumps({"event": "model_load_failed", "error_type": type(error).__name__}))
            async with AsyncExitStack() as stack:
                app.state.agent_host = agent_host
                if agent_host is None and os.environ.get('AQUAMIND_AGENT_ENABLED') == '1':
                    try:
                        from openai import AsyncOpenAI
                        from .agent import AgentConfig
                        from .agent_http import AgentHost
                        key = os.environ.get('OPENAI_API_KEY', '').strip()
                        if not key:
                            raise ValueError('OpenAI key missing')
                        config = AgentConfig(model=os.environ.get('OPENAI_MODEL', '').strip())
                        provider = await stack.enter_async_context(AsyncOpenAI(
                            api_key=key,
                            base_url='https://api.openai.com/v1', max_retries=0, timeout=30))
                        app.state.agent_host = AgentHost(provider, config,
                            detector=app.state.detector, detector_lock=lock)
                    except Exception as error:
                        logger.error(json.dumps({'event': 'agent_configuration_failed',
                                                 'error_type': type(error).__name__}))
                yield
        finally:
            app.state.agent_host = None
            app.state.detector = None
            torch.set_num_threads(previous_threads)

    app = FastAPI(title="AquaMind inference", version="0.1.0", lifespan=lifespan)
    app.state.sessions = sessions if sessions is not None else DemoSessions()
    app.include_router(approval_router(app.state.sessions))
    app.include_router(bill_router(app.state.sessions))
    from .agent_http import agent_router
    app.include_router(agent_router(app.state.sessions))

    @app.middleware("http")
    async def trace(request: Request, call_next):
        request.state.request_id = str(uuid4())
        start = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        logger.info(json.dumps({"event": "request", "request_id": request.state.request_id,
                                "status": response.status_code,
                                "elapsed_ms": round((perf_counter() - start) * 1000, 3)}))
        return response

    @app.exception_handler(ApprovalSessionUnavailable)
    async def inactive_session(request: Request, error):
        # Handles expiry/revocation after registry lookup but before store use.
        return JSONResponse(status_code=401, content={"detail": "Session unavailable",
                            "request_id": request.state.request_id})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error):
        # Do not reflect raw input, NaN, or exception objects in validation errors.
        return JSONResponse(status_code=422, content={"detail": "Invalid request",
                            "request_id": request.state.request_id})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        detector = app.state.detector
        if detector is None:
            raise HTTPException(503, "Model unavailable")
        return {"status": "ready", "model_version": detector.version}

    @app.post("/v1/anomaly/predict", response_model=PredictionResponse)
    def predict(body: PredictionRequest, request: Request):
        detector = app.state.detector
        if detector is None:
            raise HTTPException(503, "Model unavailable")
        start = datetime.fromisoformat(body.start_timestamp)
        # The inference adapter carries no caller-supplied labels or scenario identity.
        window = MeterWindow(tuple(body.flow_rates_gpm), 0, "normal", False, False,
                             body.start_timestamp, (start + timedelta(minutes=95 * 15)).isoformat())
        try:
            # Serialize access because the detector preserves model train/eval mode internally.
            with lock:
                prediction = detector.predict((window,))[0]
            return PredictionResponse(**prediction, threshold=detector.manifest["threshold"],
                                      request_id=request.state.request_id)
        except Exception as error:
            logger.error(json.dumps({"event": "inference_failed", "request_id": request.state.request_id,
                                     "error_type": type(error).__name__}))
            raise HTTPException(503, "Inference unavailable") from None

    return app


app = create_app()
