"""A2A AgentExecutor that routes AP3 protocol envelopes around the LLM.

The split is structural:

    Part.data  (ProtocolEnvelope) -> ProtocolHandler
    Part.text  (natural language) -> optional inner AgentExecutor (LLM)

No string matching on text parts. No chance of prompt injection smuggling
protocol bytes. No chance of the LLM silently corrupting ciphertext.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Task, TaskState, TaskStatus
from a2a.utils.errors import UnsupportedOperationError

from ap3.a2a.wire import ProtocolEnvelope, envelope_from_parts

logger = logging.getLogger(__name__)


class ProtocolHandler(Protocol):
    """Contract between PrivacyAgentExecutor and the PrivacyAgent it belongs to.

    The agent implements this; the executor calls it. Keeping this small
    keeps the executor reusable — a framework integration can wrap the
    executor without depending on the whole PrivacyAgent.
    """

    async def handle_envelope(
        self, envelope: ProtocolEnvelope
    ) -> Optional[ProtocolEnvelope]:
        """Process one inbound envelope.

        Returning an envelope means "send this back as the task artifact
        on this same A2A call." Returning None means "acknowledged; the
        next phase (if any) will go out on a fresh A2A call to the peer."
        Most phases return None — the PSI msg2 reply is the exception.
        """
        ...


class PrivacyAgentExecutor(AgentExecutor):
    """A2A executor that handles AP3 protocol traffic directly.

    If the incoming message carries no AP3 envelope, it is forwarded to an
    optional inner executor (e.g. a Google ADK / LangChain executor that
    owns the LLM). This lets a single HTTP server both run the protocol
    and answer natural-language questions about it.
    """

    def __init__(
        self,
        *,
        protocol_handler: ProtocolHandler,
        llm_executor: Optional[AgentExecutor] = None,
    ) -> None:
        self._handler = protocol_handler
        self._llm = llm_executor

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        # a2a-sdk v1.x expects the task to exist in the stream before any
        # TaskStatusUpdateEvent. The request handler will persist/create the task,
        # but we also enqueue an initial Task event to satisfy strict stream
        # ordering validation.
        if not context.current_task:
            await event_queue.enqueue_event(
                Task(
                    id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                )
            )
            await updater.update_status(TaskState.TASK_STATE_SUBMITTED)
        await updater.update_status(TaskState.TASK_STATE_WORKING)

        try:
            envelope = envelope_from_parts(list(context.message.parts))
        except ValueError as exc:
            # Multi-envelope, oversized envelope, or malformed envelope from
            # `envelope_from_parts`. Refuse cleanly with a structured failure
            # rather than letting it surface as an unhandled 500. We don't
            # have an envelope to bind a reply to, so we just close the task
            # in a failed state — the peer's `send_envelope` will see no
            # AP3 reply artifact and surface the failure to the caller.
            logger.warning("rejecting inbound parts: %s", exc)
            await updater.update_status(TaskState.TASK_STATE_FAILED)
            return
        if envelope is not None:
            await self._dispatch_protocol(envelope, updater)
            return

        if self._llm is not None:
            await self._llm.execute(context, event_queue)
            return

        # No envelope and no LLM: the agent is protocol-only. Complete the
        # task with no artifact so the peer doesn't hang.
        await updater.complete()

    async def _dispatch_protocol(
        self,
        envelope: ProtocolEnvelope,
        updater: TaskUpdater,
    ) -> None:
        reply = await self._handler.handle_envelope(envelope)
        if reply is None:
            await updater.complete()
            return
        from ap3.a2a.wire import envelope_to_part  # avoid cycle at module load
        await updater.add_artifact([envelope_to_part(reply)], last_chunk=True)
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # AP3 protocol rounds are short-lived and self-terminating. Until
        # we have a concrete cancellation story, delegate to the LLM side
        # if present, otherwise refuse.
        if self._llm is not None:
            await self._llm.cancel(context, event_queue)
            return
        raise UnsupportedOperationError()
