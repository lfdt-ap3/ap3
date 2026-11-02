"""File Notes:
- Minimal generic operation contract for external protocol builders.
- Sessions are owned by the Operation instance — no separate registry needed.
- `receive()` calls `on_process()` with empty state and `context.is_first_message=True`.
- Subclasses implement `on_start()` and `on_process()` for protocol logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
import uuid
from typing import Any, ClassVar, Dict, Optional

OperationInputs = Dict[str, Any] | list[Any] | tuple[Any, ...] | str | int | float | bool | None

_REFUSAL_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


class OperationRefusal(Exception):
    """Raised by an operation to refuse with a code the initiator sees.

    Any other exception still reaches the initiator as OPERATION_ERROR, so only
    what the operation chooses to say leaves the receiver.
    """

    def __init__(self, code: str, message: str = "") -> None:
        if not _REFUSAL_CODE.fullmatch(code):
            raise ValueError("refusal code must be UPPER_SNAKE_CASE, 2 to 64 characters")
        super().__init__(message or code)
        self.code = code
        self.message = message[:200]

@dataclass
class OperationResult:
    next_state: Dict[str, Any] = field(default_factory=dict)
    done: bool = False
    outgoing: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, session_id: str, operation_id: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "session_id": session_id,
            "operation": operation_id,
            "done": self.done,
            "metadata": self.metadata,
        }
        if self.outgoing is not None:
            out["outgoing"] = self.outgoing
        if self.result is not None:
            out["result"] = self.result
        return out


@dataclass(slots=True)
class _Session:
    role: str
    state: Dict[str, Any]
    config: Dict[str, Any]


class Operation(ABC):
    operation_id: ClassVar[str]

    def __init__(self) -> None:
        self._sessions: Dict[str, _Session] = {}

    def _save_session(
        self,
        session_id: str,
        role: str,
        state: Dict[str, Any],
        config: Dict[str, Any],
    ) -> None:
        self._sessions[session_id] = _Session(
            role=role,
            state=dict(state),
            config=dict(config),
        )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        operation_id = getattr(cls, "operation_id", "")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise TypeError(f"{cls.__name__} must define a non-empty 'operation_id'")

    def start(
        self,
        role: str,
        inputs: OperationInputs = None,
        config: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initiate a new session by calling on_start()."""
        config = config or {}
        sid = session_id or uuid.uuid4().hex
        result = self.on_start(
            role=role,
            inputs=inputs,
            config=config,
            context=context or {},
        )
        if not result.done:
            self._save_session(sid, role, result.next_state, config)
        return result.to_dict(sid, self.operation_id)

    def receive(
        self,
        role: str,
        message: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle the first inbound message (responder side).

        Calls on_process() with empty state and is_first_message=True.
        """
        config = config or {}
        sid = session_id or uuid.uuid4().hex
        ctx = dict(context or {})
        ctx.setdefault("is_first_message", True)
        result = self.on_process(
            role=role,
            state={},
            message=message,
            config=config,
            context=ctx,
        )
        if not result.done:
            self._save_session(sid, role, result.next_state, config)
        return result.to_dict(sid, self.operation_id)

    def process(
        self,
        session_id: str,
        message: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Handle a subsequent protocol round for an existing session."""
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        ctx = dict(context or {})
        ctx.setdefault("is_first_message", False)
        try:
            result = self.on_process(
                role=session.role,
                state=dict(session.state),
                message=message,
                config=session.config,
                context=ctx,
            )
        except Exception:
            # A failed round ends the session. Without this, only a clean
            # `done` removed it, so every malformed round a peer sent left
            # its state behind for good.
            self.abort(session_id)
            raise
        if result.done:
            self._sessions.pop(session_id, None)
        else:
            session.state = dict(result.next_state) 
        return result.to_dict(session_id, self.operation_id)

    def has_session(self, session_id: str) -> bool:
        """Return True if a session with this ID is currently active."""
        return session_id in self._sessions

    def abort(self, session_id: str) -> bool:
        """End a session and discard its state.

        For errors, cancellation and expiry. Returns True if a session was
        removed, False if there was none.
        """
        return self._sessions.pop(session_id, None) is not None

    @abstractmethod
    def on_start(
        self,
        role: str,
        inputs: OperationInputs,
        config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> OperationResult:
        """Called when a new session is initiated via start()."""
        ...

    @abstractmethod
    def on_process(
        self,
        role: str,
        state: Dict[str, Any],
        message: Dict[str, Any],
        config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> OperationResult:
        """Called for every protocol round (both receive() and process())."""
        ...
