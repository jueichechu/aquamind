"""Session-local goal approvals. Only the trusted host may call decide()."""

from dataclasses import dataclass, replace
from threading import Lock
from time import monotonic
from typing import Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ApprovalSessionUnavailable(RuntimeError):
    """The owning session expired or was revoked."""


class GoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    daily_gallons: float = Field(strict=True, gt=0, le=10_000, allow_inf_nan=False)


class GoalProposal(BaseModel):
    model_config = ConfigDict(frozen=True)
    approval_id: str
    status: Literal["approval_required", "approved", "rejected", "expired", "conflict"]
    action: Literal["set_conservation_goal"] = "set_conservation_goal"
    arguments: GoalRequest
    summary: str
    expected_revision: int
    expires_in_seconds: float


@dataclass(frozen=True)
class _Entry:
    proposal: GoalProposal
    deadline: float


class GoalApprovals:
    """One trusted host session owns one instance; never share across users.

    Proposals do not modify the goal. Decisions are host-only, atomic, bounded,
    expire after ten minutes, and reject stale revisions. No persistence yet.
    """

    def __init__(self, *, clock: Callable[[], float] = monotonic,
                 session_deadline: float | None = None):
        self._clock = clock
        self._lock = Lock()
        self._entries: dict[str, _Entry] = {}
        self._goal: GoalRequest | None = None
        self._revision = 0
        self._session_deadline = session_deadline
        self._revoked = False

    def invalidate(self) -> None:
        """Revoke cached references as well as registry access; safe to repeat."""
        with self._lock:
            self._revoked = True
            self._entries.clear()
            self._goal = None

    def _require_active(self) -> None:
        # Called while holding the same lock used by goal mutations and revoke.
        if self._revoked or (self._session_deadline is not None and
                             self._clock() >= self._session_deadline):
            self._entries.clear()
            self._goal = None
            raise ApprovalSessionUnavailable("Session unavailable")

    @property
    def goal(self) -> GoalRequest | None:
        with self._lock:
            self._require_active()
            return self._goal

    def propose(self, request: GoalRequest) -> GoalProposal:
        # Revalidate at the boundary even if a caller supplied a constructed model.
        request = GoalRequest.model_validate(request.model_dump())
        with self._lock:
            self._require_active()
            if len(self._entries) >= 100:
                raise ValueError("Approval capacity reached; start a new host session")
            now = self._clock()
            deadline = min(now + 600, self._session_deadline) if self._session_deadline is not None else now + 600
            proposal = GoalProposal(approval_id=str(uuid4()), status="approval_required",
                                    arguments=request,
                                    summary=f"Set your daily conservation goal to {request.daily_gallons} gallons.",
                                    expected_revision=self._revision, expires_in_seconds=deadline - now)
            self._entries[proposal.approval_id] = _Entry(proposal, deadline)
            return proposal

    def review(self, approval_id: str) -> GoalProposal:
        """Return the exact stored proposal with a current expiry countdown."""
        with self._lock:
            self._require_active()
            entry = self._entries.get(approval_id)
            if entry is None:
                raise LookupError("Unknown approval")
            proposal = entry.proposal
            remaining = max(0, entry.deadline - self._clock())
            if proposal.status == "approval_required" and remaining == 0:
                proposal = proposal.model_copy(update={"status": "expired", "expires_in_seconds": 0})
                self._entries[approval_id] = replace(entry, proposal=proposal)
            return proposal.model_copy(update={"expires_in_seconds": remaining
                                       if proposal.status == "approval_required" else 0})

    def decide(self, approval_id: str, decision: Literal["approve", "reject"]) -> GoalProposal:
        """Trusted host entry point after a human decision; never register as a tool.

        The host must bind this instance to its user/session and display the exact
        proposal before calling. An agent-supplied approval flag is not consent.
        """
        if decision not in ("approve", "reject"):
            raise ValueError("Expected approve or reject")
        with self._lock:
            self._require_active()
            entry = self._entries.get(approval_id)
            if entry is None:
                raise LookupError("Unknown approval")
            proposal = entry.proposal
            if proposal.status != "approval_required":
                # Retries return the original outcome; cannot re-execute or reverse it.
                return proposal
            if self._clock() >= entry.deadline:
                status = "expired"
            elif decision == "reject":
                status = "rejected"
            elif proposal.expected_revision != self._revision:
                status = "conflict"
            else:
                self._goal = proposal.arguments
                self._revision += 1
                status = "approved"
            outcome = proposal.model_copy(update={"status": status, "expires_in_seconds": 0})
            self._entries[approval_id] = replace(entry, proposal=outcome)
            return outcome
