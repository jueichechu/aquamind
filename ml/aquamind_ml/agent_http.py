"""Opt-in, bounded single-turn agent host using the existing demo session boundary."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from weakref import WeakKeyDictionary

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .approvals import GoalApprovals, GoalProposal
from .sessions import DemoSessions, require_session
from .demo_meter import DEFAULT_DEMO_METER_PATH, DemoMeterStore
from .weather import ScenarioId

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from .agent import AgentConfig, AgentPause, AgentResult


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=8192)
    scenario_id: ScenarioId | None = None

    @field_validator('text')
    @classmethod
    def bounded_text(cls, value):
        if not value.strip() or len(value.encode()) > 8192:
            raise ValueError('Expected 1–8192 bytes of text')
        return value


class AgentTurnResponse(BaseModel):
    status: Literal['answer', 'approval_required', 'refused', 'limit_reached', 'unavailable', 'unconfirmed']
    answer: str
    pending_approval: GoalProposal | None
    error: str | None
    model_calls: int
    model_trace: list[dict]
    tool_trace: list[dict]
    request_id: str


class AgentContinueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    approval_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


@dataclass
class _Continuation:
    approval_id: str
    pause: AgentPause | None
    scenario_id: ScenarioId | None = None
    attempted: bool = False
    result: AgentResult | None = None


class AgentHost:
    """One event loop/process; fixed local-demo limits, never an approval authority."""

    def __init__(self, client: AsyncOpenAI, config: AgentConfig, *,
                 demo_meter_path=DEFAULT_DEMO_METER_PATH):
        self.client, self.config = client, config
        self._active: set[GoalApprovals] = set()
        self._counts: WeakKeyDictionary[GoalApprovals, int] = WeakKeyDictionary()
        self._continuations: WeakKeyDictionary[GoalApprovals, _Continuation] = WeakKeyDictionary()
        self._total = 0
        try:
            self._demo_meter = DemoMeterStore(demo_meter_path)
        except Exception:
            # Unselected turns remain usable; selected meter requests fail before provider work.
            self._demo_meter = None

    def _server(self, store, scenario_id, *, allow_goals):
        from .mcp_server import create_server
        scopes = {'weather:read', 'utility:read'}
        allowed = {'get_weather_context', 'get_utility_rate', 'estimate_water_cost',
                   'estimate_conservation_savings'}
        if allow_goals:
            scopes.add('goals:write')
            allowed.add('set_conservation_goal')
        if scenario_id is not None:
            if self._demo_meter is None:
                raise HTTPException(503, 'Demo meter unavailable')
            scopes.add('meter:read')
            allowed.update({'get_meter_summary', 'get_meter_series'})
        return create_server(None, frozenset(scopes), goal_approvals=store,
                             demo_meter=self._demo_meter, demo_scenario=scenario_id), frozenset(allowed)

    @asynccontextmanager
    async def _slot(self, store: GoalApprovals):
        _ = store.goal  # Uses the store's locked expiry/revocation check.
        # No awaits between admission checks and reservation on the host's event loop.
        if store in self._active:
            raise HTTPException(409, 'An agent turn is already running for this session')
        if len(self._active) >= 2:
            raise HTTPException(429, 'Agent is busy')
        if self._total >= 100 or self._counts.get(store, 0) >= 8:
            raise HTTPException(429, 'Local demo agent budget exhausted')
        self._active.add(store)
        self._counts[store] = self._counts.get(store, 0) + 1
        self._total += 1
        try:
            yield
        except HTTPException:
            raise
        except Exception:
            _ = store.goal  # Map revocation/expiry during provider or transport work to 401.
            raise HTTPException(503, 'Agent unavailable') from None
        finally:
            self._active.discard(store)

    async def run(self, text: str, store: GoalApprovals, *,
                  scenario_id: ScenarioId | None = None) -> AgentResult:
        # Lazy imports keep inference-only installations independent of the agent SDK.
        from mcp import Client
        from .agent import run_agent
        from .agent_tools import McpAgentTools

        def check_active():
            _ = store.goal

        check_active()
        previous = self._continuations.get(store)
        if previous is not None and store.review(previous.approval_id).status == 'approval_required':
            raise HTTPException(409, 'Resolve the pending goal before starting another question')
        async with self._slot(store):
            self._continuations.pop(store, None)
            pauses = []
            server, allowed = self._server(store, scenario_id, allow_goals=True)
            async with Client(server) as mcp:
                outcome = await run_agent(text, self.client, McpAgentTools(mcp, allowed), self.config,
                                          check_active=check_active, on_pause=pauses.append)
            check_active()
            if outcome.status == 'approval_required' and pauses:
                self._continuations[store] = _Continuation(
                    outcome.pending_approval['approval_id'], pauses[0], scenario_id)
            return outcome

    async def continue_after_decision(self, approval_id: str, store: GoalApprovals) -> AgentResult:
        from mcp import Client
        from .agent import continue_agent
        from .agent_tools import McpAgentTools

        def check_active():
            _ = store.goal

        check_active()
        entry = self._continuations.get(store)
        if entry is None or entry.approval_id != approval_id:
            raise HTTPException(404, 'Agent continuation not found')
        if store in self._active:
            raise HTTPException(409, 'An agent turn is already running for this session')
        if entry.attempted:
            if entry.result is None:
                raise HTTPException(503, 'Continuation outcome unconfirmed; start a new question')
            return entry.result
        decision = store.review(approval_id)
        if decision.status == 'approval_required':
            raise HTTPException(409, 'A trusted decision is required before continuing')
        async with self._slot(store):
            entry.attempted = True  # Consume before awaiting; interruption must never trigger a second paid attempt.
            try:
                server, allowed = self._server(store, entry.scenario_id, allow_goals=False)
                async with Client(server) as mcp:
                    entry.result = await continue_agent(entry.pause, decision, store.goal, self.client,
                        McpAgentTools(mcp, allowed), self.config, check_active=check_active)
                check_active()
                return entry.result
            finally:
                entry.pause = None  # Drop original prompts and encrypted protocol items after the one attempt.


def agent_router(sessions: DemoSessions) -> APIRouter:
    router = APIRouter()

    async def body_for(request: Request, schema, limit):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Expected application/json')
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > limit:
                raise HTTPException(413, 'Request too large')
            raw.extend(chunk)
        try:
            return schema.model_validate_json(bytes(raw))
        except ValidationError:
            raise HTTPException(422, 'Invalid agent request') from None

    def host_for(request):
        host = request.app.state.agent_host
        if host is None:
            raise HTTPException(503, 'Agent unavailable')
        return host

    @router.post('/v1/agent/turn', response_model=AgentTurnResponse)
    async def turn(request: Request):
        store = require_session(sessions, request)
        host = host_for(request)
        body = await body_for(request, AgentTurnRequest, 16384)
        outcome = await host.run(body.text, store, scenario_id=body.scenario_id)
        # Re-read a pending proposal from this session's authoritative store.
        public = outcome.public_dict()
        if outcome.pending_approval is not None:
            public['pending_approval'] = store.review(outcome.pending_approval['approval_id'])
        return AgentTurnResponse(**public, request_id=request.state.request_id)

    @router.post('/v1/agent/continue', response_model=AgentTurnResponse)
    async def continue_turn(request: Request):
        store = require_session(sessions, request)
        host = host_for(request)
        body = await body_for(request, AgentContinueRequest, 1024)
        outcome = await host.continue_after_decision(body.approval_id, store)
        return AgentTurnResponse(**outcome.public_dict(), request_id=request.state.request_id)

    return router
