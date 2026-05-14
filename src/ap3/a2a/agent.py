"""PrivacyAgent — the one thing a developer touches.

Example usage on an initiator:

    from ap3.a2a import PrivacyAgent
    from ap3.signing.primitives import generate_keypair
    from ap3_functions import PSIOperation
    from ap3.types import CommitmentMetadata, Industry, DataFormat, DataStructure, DataFreshness

    private_key, public_key = generate_keypair()
    agent = PrivacyAgent(
        name="Company A PSI Initiator",
        description="Runs PSI against partner sanction lists",
        card_url="https://psi.companya.com",
        port=10002,
        role="ap3_initiator",
        operation=PSIOperation(),
        commitment=CommitmentMetadata(...),
        private_key=private_key,
        public_key=public_key,
    )
    async with agent.serving():
        result = await agent.run_intent(
            peer_url="https://psi.companyb.com",
            inputs={"customer_data": "John Doe,ID123,123 Main St"},
        )
        print(result.result_data.metadata["description"])

On a receiver the call is just `async with agent.serving(): await agent.wait()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Callable, Optional

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn

from ap3 import __version__ as _AP3_VERSION
from ap3.a2a._core import DEFAULT_INTENT_EXPIRY_HOURS, _ProtocolCore
from ap3.a2a.card import build_privacy_agent_card, extract_peer_info
from ap3.a2a.client import PeerClient
from ap3.a2a.executor import PrivacyAgentExecutor, ProtocolHandler
from ap3.a2a.wire import ProtocolEnvelope
from ap3.core.operation import Operation
from ap3.services.commitment import CommitmentMetadataSystem
from ap3.types import (
    CommitmentMetadata,
    PrivacyResultDirective,
)

logger = logging.getLogger(__name__)


class PrivacyAgent(ProtocolHandler):
    """The whole agent: card + server + protocol logic + outbound client.

    One instance per process. Binds to a port and owns an AP3 `Operation`
    and an Ed25519 keypair. The same class is used for both initiators and
    receivers; role is declared at construction and determines which
    methods are safe to call.

    Protocol flow (response-based, N-round):
    - `run_intent` loops: send outgoing → read reply → `operation.process`
      → send next outgoing → ... until the Operation reports `done`.
    - Receiver handles inbound envelopes one at a time, persisting session
      state keyed by wire session id; first inbound for a session calls
      `operation.receive`, later ones call `operation.process`.
    - PSI is the 2-round degenerate case: initiator's first `process` is
      already `done`, and receiver's `receive` is already `done`.
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        card_url: str,
        port: int,
        role: str,
        operation: Operation,
        commitment: CommitmentMetadata | list[CommitmentMetadata],
        private_key: bytes,
        public_key: bytes,
        host: str = "127.0.0.1",
        peer_client: Optional[PeerClient] = None,
        skill_id: Optional[str] = None,
        skill_name: Optional[str] = None,
        skill_description: Optional[str] = None,
        skill_examples: Optional[list[str]] = None,
        receiver_config_provider: Optional[Callable[[], dict]] = None,
        llm_executor: Optional[Any] = None,
        compatibility_scorer: Optional[
            Callable[[Any, Any, Optional[str]], tuple[float, str]]
        ] = None,
        allow_private_initiator_urls: bool = False,
    ) -> None:
        if role not in ("ap3_initiator", "ap3_receiver"):
            raise ValueError(f"unknown role: {role}")
        operation_type = getattr(operation, "operation_type", None)
        if not isinstance(operation_type, str) or not operation_type:
            raise TypeError(
                f"{type(operation).__name__} must declare a class attr "
                f"`operation_type` (e.g. 'PSI')"
            )

        self._name = name
        self._role = role
        self._host = host
        self._port = port

        if isinstance(commitment, list):
            if len(commitment) != 1:
                raise ValueError(
                    "PrivacyAgent currently supports exactly one commitment; "
                    f"got {len(commitment)}"
                )
            commitment_obj = commitment[0]
        else:
            commitment_obj = commitment

        # Ensure commitments published on the AgentCard are signed by the same
        # Ed25519 key that the card advertises (trust anchor for peers).
        if not commitment_obj.signature:
            sig = CommitmentMetadataSystem.sign_commitment(commitment_obj, private_key)
            commitment_obj = commitment_obj.model_copy(update={"signature": sig})

        self._card = build_privacy_agent_card(
            name=name,
            description=description,
            version="1.0.0",
            card_url=card_url,
            skill_id=skill_id or operation.operation_id,
            skill_name=skill_name or operation_type,
            skill_description=skill_description or f"{operation_type} over AP3",
            skill_examples=skill_examples or [],
            roles=[role],
            supported_operations=[operation_type],
            commitments=[commitment_obj],
            public_key=public_key,
            ap3_sdk_version=_AP3_VERSION,
        )
        # Own-side ap3 params, precomputed once for the compat check.
        own_info = extract_peer_info(self._card, agent_url=card_url)
        self_url = self._card.supported_interfaces[0].url.rstrip("/")

        self._core = _ProtocolCore(
            operation=operation,
            operation_type=operation_type,
            private_key=private_key,
            peer_client=peer_client or PeerClient(),
            own_info=own_info,
            self_url=self_url,
            config_provider=receiver_config_provider,
            compatibility_scorer=compatibility_scorer,
            allow_private_initiator_urls=allow_private_initiator_urls,
        )

        # Import A2A/HTTP server dependencies lazily so importing `ap3` does
        # not require the `ap3[a2a]` extra unless the user actually
        # constructs a PrivacyAgent.
        try:
            import uvicorn  # type: ignore
            from starlette.applications import Starlette  # type: ignore
            from starlette.routing import Route  # type: ignore

            from a2a.server.request_handlers import DefaultRequestHandler  # type: ignore
            from a2a.server.routes import (  # type: ignore
                create_agent_card_routes,
                create_jsonrpc_routes,
            )
            from a2a.server.tasks import InMemoryTaskStore  # type: ignore
        except Exception as e:  # pragma: no cover
            raise ImportError(
                "PrivacyAgent requires the A2A server dependencies. "
                "Install with `pip install ap3[a2a]`."
            ) from e

        self._uvicorn = uvicorn
        executor = PrivacyAgentExecutor(
            protocol_handler=self,
            llm_executor=llm_executor,
        )
        request_handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
            agent_card=self._card,
        )
        routes: list[Route] = [  # type: ignore[name-defined]
            *create_agent_card_routes(self._card),
            *create_jsonrpc_routes(request_handler, rpc_url="/"),
        ]
        self._app = Starlette(routes=routes)
        self._server: Optional["uvicorn.Server"] = None

    # ---- lifecycle ---------------------------------------------------

    @contextlib.asynccontextmanager
    async def serving(self):
        """Start the HTTP server for the duration of the context."""
        config = self._uvicorn.Config(
            self._app, host=self._host, port=self._port, log_level="info"
        )
        self._server = self._uvicorn.Server(config)
        task = asyncio.create_task(self._server.serve())
        try:
            while not self._server.started:
                await asyncio.sleep(0.05)
            yield self
        finally:
            self._server.should_exit = True
            await task

    async def wait(self) -> None:
        """Block forever while serving. Receiver's main-loop helper."""
        if self._server is None:
            raise RuntimeError("wait() requires serving() context")
        while not self._server.should_exit:
            await asyncio.sleep(3600)

    # ---- initiator API -----------------------------------------------

    async def run_intent(
        self,
        *,
        peer_url: str,
        inputs: Any,
        expiry_hours: int = DEFAULT_INTENT_EXPIRY_HOURS,
    ) -> PrivacyResultDirective:
        if self._role != "ap3_initiator":
            raise RuntimeError("run_intent() is only valid for initiators")
        return await self._core.run_intent(
            peer_url=peer_url, inputs=inputs, expiry_hours=expiry_hours
        )

    # ---- ProtocolHandler impl (inbound) ------------------------------

    async def handle_envelope(
        self, envelope: ProtocolEnvelope
    ) -> Optional[ProtocolEnvelope]:
        if self._role != "ap3_receiver":
            logger.warning(
                "initiator received inbound envelope; response-based flow "
                "does not expect this — dropping"
            )
            return None
        return await self._core.handle_envelope(envelope)
