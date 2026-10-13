"""A2A extension-activation invariants for the AP3 executor.

Two spec-mandated behaviors are covered here:

- The extension URI on the AgentCard must be *versioned* (a plain
  `github.com/lfdt-ap3/ap3` was refused by strict A2A consumers).
- When the extension is declared `required=True`, the server MUST reject a
  request that did not activate it via the `A2A-Extensions` HTTP header —
  otherwise a client that never opted in could still smuggle envelopes
  through.
"""

from __future__ import annotations

import asyncio

import pytest

from a2a.server.agent_execution.context import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import Message, Role, SendMessageRequest, TaskState

from ap3.a2a.card import AP3_EXTENSION_URI
from ap3.a2a.executor import PrivacyAgentExecutor
from ap3.a2a.wire import ProtocolEnvelope, envelope_to_part


def test_ap3_extension_uri_is_versioned():
    """A2A spec MUSTs the URI carry a version segment."""
    assert AP3_EXTENSION_URI.rstrip("/").endswith("/v1"), AP3_EXTENSION_URI


class _RecordingHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def handle_envelope(self, envelope):
        self.calls += 1
        return None


def _request_context(*, activated: bool) -> tuple[RequestContext, EventQueue]:
    envelope = ProtocolEnvelope(
        operation="psi", phase="msg1", session_id="sid-test", payload="p"
    )
    message = Message(role=Role.ROLE_USER, message_id="mid-1")
    message.parts.append(envelope_to_part(envelope))
    request = SendMessageRequest(message=message)

    requested = {AP3_EXTENSION_URI} if activated else set()
    call_context = ServerCallContext(requested_extensions=requested)
    context = RequestContext(call_context=call_context, request=request)
    return context, EventQueue()


@pytest.mark.asyncio
async def test_executor_rejects_when_extension_not_activated():
    handler = _RecordingHandler()
    executor = PrivacyAgentExecutor(protocol_handler=handler)

    context, queue = _request_context(activated=False)
    await executor.execute(context, queue)

    # Handler must never be reached — the header check fires first.
    assert handler.calls == 0

    # Drain the queue and check the terminal state is REJECTED.
    seen_states: list[int] = []
    while True:
        try:
            ev = await asyncio.wait_for(queue.dequeue_event(), timeout=0.1)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            break
        status = getattr(ev, "status", None)
        if status is not None:
            seen_states.append(status.state)
        # Task events also carry a status
        task = getattr(ev, "id", None) and ev
        if task is not None and hasattr(task, "status"):
            seen_states.append(task.status.state)
    assert TaskState.TASK_STATE_REJECTED in seen_states


@pytest.mark.asyncio
async def test_executor_accepts_when_extension_activated():
    handler = _RecordingHandler()
    executor = PrivacyAgentExecutor(protocol_handler=handler)

    context, queue = _request_context(activated=True)
    await executor.execute(context, queue)

    assert handler.calls == 1
