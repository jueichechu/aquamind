"""Opt-in, bounded single-turn agent host using the existing demo session boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from weakref import WeakKeyDictionary

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .approvals import GoalApprovals, GoalProposal
from .sessions import DemoSessions, require_session

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from .agent import AgentConfig, AgentResult


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=8192)

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


class AgentHost:
    """One event loop/process; fixed local-demo limits, never an approval authority."""

    def __init__(self, client: AsyncOpenAI, config: AgentConfig):
        self.client, self.config = client, config
        self._active: set[GoalApprovals] = set()
        self._counts: WeakKeyDictionary[GoalApprovals, int] = WeakKeyDictionary()
        self._total = 0

    async def run(self, text: str, store: GoalApprovals) -> AgentResult:
        # Lazy imports keep inference-only installations independent of the agent SDK.
        from mcp import Client
        from .agent import run_agent
        from .agent_tools import McpAgentTools
        from .mcp_server import create_server

        def check_active():
            _ = store.goal  # Uses the store's locked expiry/revocation check.

        check_active()
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
            scopes = frozenset({'weather:read', 'utility:read', 'goals:write'})
            allowed = frozenset({'get_weather_context', 'get_utility_rate', 'estimate_water_cost',
                                 'estimate_conservation_savings', 'set_conservation_goal'})
            async with Client(create_server(None, scopes, goal_approvals=store)) as mcp:
                outcome = await run_agent(text, self.client, McpAgentTools(mcp, allowed), self.config,
                                          check_active=check_active)
            check_active()
            return outcome
        except HTTPException:
            raise
        except Exception:
            check_active()  # Expired/revoked sessions remain 401, including during MCP setup.
            raise HTTPException(503, 'Agent unavailable') from None
        finally:
            self._active.discard(store)


def agent_router(sessions: DemoSessions) -> APIRouter:
    router = APIRouter()

    @router.post('/v1/agent/turn', response_model=AgentTurnResponse)
    async def turn(request: Request):
        store = require_session(sessions, request)
        host = request.app.state.agent_host
        if host is None:
            raise HTTPException(503, 'Agent unavailable')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Expected application/json')
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 16384:
                raise HTTPException(413, 'Request too large')
            raw.extend(chunk)
        try:
            body = AgentTurnRequest.model_validate_json(bytes(raw))
        except ValidationError:
            raise HTTPException(422, 'Invalid agent request') from None
        outcome = await host.run(body.text, store)
        # Re-read a pending proposal from this session's authoritative store.
        public = outcome.public_dict()
        if outcome.pending_approval is not None:
            public['pending_approval'] = store.review(outcome.pending_approval['approval_id'])
        return AgentTurnResponse(**public, request_id=request.state.request_id)

    return router
