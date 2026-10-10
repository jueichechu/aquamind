"""Bounded ephemeral demo sessions; bearer credentials stay with the trusted host."""

from dataclasses import dataclass
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .approvals import GoalApprovals, GoalProposal, GoalRequest


@dataclass(frozen=True)
class _Session:
    approvals: GoalApprovals
    deadline: float


class DemoSessions:
    def __init__(self, *, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._lock = Lock()
        self._sessions: dict[str, _Session] = {}

    def create(self) -> str:
        with self._lock:
            now = self._clock()
            self._sessions = {key: value for key, value in self._sessions.items() if value.deadline > now}
            if len(self._sessions) >= 100:
                raise ValueError("Session capacity reached")
            token = token_urlsafe(32)
            self._sessions[token] = _Session(GoalApprovals(clock=self._clock), now + 3600)
            return token

    def approvals(self, token: str) -> GoalApprovals:
        """Trusted host binds this store to its MCP server; never give tools the token."""
        with self._lock:
            session = self._sessions.get(token)
            if session is None or self._clock() >= session.deadline:
                self._sessions.pop(token, None)
                raise LookupError("Session unavailable")
            return session.approvals

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)


class SessionResponse(BaseModel):
    session_token: str
    expires_in_seconds: Literal[3600] = 3600


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


class GoalState(BaseModel):
    goal: GoalRequest | None


def approval_router(sessions: DemoSessions) -> APIRouter:
    router = APIRouter()

    def token_for(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 128:
            raise HTTPException(401, "Session required")
        return token

    def store_for(request: Request) -> GoalApprovals:
        try:
            return sessions.approvals(token_for(request))
        except LookupError:
            raise HTTPException(401, "Session unavailable") from None

    @router.post("/v1/sessions", response_model=SessionResponse, status_code=201)
    def create_session():
        try:
            return SessionResponse(session_token=sessions.create())
        except ValueError:
            raise HTTPException(503, "Session capacity reached") from None

    @router.delete("/v1/session", status_code=204)
    def revoke_session(request: Request):
        store_for(request)
        sessions.revoke(token_for(request))

    @router.get("/v1/goals/current", response_model=GoalState)
    def current_goal(request: Request):
        return GoalState(goal=store_for(request).goal)

    @router.get("/v1/approvals/{approval_id}", response_model=GoalProposal)
    def review(approval_id: str, request: Request):
        store = store_for(request)
        try:
            return store.review(approval_id)
        except LookupError:
            raise HTTPException(404, "Approval not found") from None

    @router.post("/v1/approvals/{approval_id}/decision", response_model=GoalProposal)
    def decide(approval_id: str, body: DecisionRequest, request: Request):
        store = store_for(request)
        try:
            return store.decide(approval_id, body.decision)
        except LookupError:
            raise HTTPException(404, "Approval not found") from None

    return router
