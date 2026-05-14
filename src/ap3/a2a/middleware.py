#!/usr/bin/env python3

"""AP3 as middleware for an existing A2A agent server.

This module lets you add AP3 protocol handling to an existing A2A server
*without* starting a separate `PrivacyAgent` HTTP server.

Intended usage:

- You already have an A2A server and an `AgentExecutor` for your LLM/framework.
- You want AP3 protocol traffic (ProtocolEnvelope in Part.data) to bypass the LLM.
- You also want initiator-side helpers (`run_intent`) from the same process.

Wire invariant remains unchanged: protocol messages are only recognized in
`Part.data` via `ProtocolEnvelope`; text routing is never used.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from a2a.types import AgentCard, AgentExtension
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from ap3 import __version__ as _AP3_VERSION
from ap3.a2a._core import DEFAULT_INTENT_EXPIRY_HOURS, _ProtocolCore
from ap3.a2a.card import (
    AP3_EXTENSION_URI,
    extract_peer_info,
)
from ap3.a2a.client import PeerClient
from ap3.a2a.executor import ProtocolHandler
from ap3.a2a.wire import AP3_WIRE_VERSION, ProtocolEnvelope
from ap3.core.operation import Operation
from ap3.types import (
    AP3ExtensionParameters,
    CommitmentMetadata,
    PrivacyResultDirective,
)

logger = logging.getLogger(__name__)


def attach_ap3_extension(
    card: AgentCard,
    *,
    roles: list[str],
    supported_operations: list[str],
    commitments: list[CommitmentMetadata],
    public_key: bytes,
    ap3_sdk_version: str = _AP3_VERSION,
) -> AgentCard:
    """Attach (or replace) the AP3 extension block on an existing AgentCard.

    Many agent frameworks already build and serve their own AgentCard. This helper
    adds the AP3 params in-place so peers can discover your AP3 capability and
    verify signed directives.
    """
    if len(public_key) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(public_key)}")

    params = Struct()
    params.update(
        {
            "ap3_version": ap3_sdk_version,
            "ap3_wire_version": AP3_WIRE_VERSION,
            "public_key_hex": public_key.hex(),
            "roles": list(roles),
            "supported_operations": list(supported_operations),
            "commitments": [c.model_dump(mode="json") for c in commitments],
        }
    )

    ext = AgentExtension(
        uri=AP3_EXTENSION_URI,
        description="AP3 privacy-preserving operations",
        required=True,
    )
    ext.params.CopyFrom(params)

    # Replace any existing AP3 extension to avoid duplicates.
    kept: list[AgentExtension] = [
        e for e in card.capabilities.extensions if e.uri != AP3_EXTENSION_URI
    ]
    kept.append(ext)
    del card.capabilities.extensions[:]
    card.capabilities.extensions.extend(kept)
    return card


@dataclass(frozen=True)
class AP3Identity:
    """AP3 identity inputs for middleware mode."""

    card: AgentCard
    card_url: str
    private_key: bytes
    public_key: bytes
    role: str  # "ap3_initiator" | "ap3_receiver"
    operation_type: str  # e.g. "PSI"

    @property
    def self_url(self) -> str:
        # Prefer the declared card_url (usually what is externally reachable).
        return self.card_url.rstrip("/")


class AP3Middleware(ProtocolHandler):
    """A ProtocolHandler you can embed into an existing A2A server.

    - Inbound envelopes: call `handle_envelope()` via `PrivacyAgentExecutor`.
    - Outbound initiator runs: call `run_intent()` from your app code.
    """

    def __init__(
        self,
        *,
        identity: AP3Identity,
        operation: Operation,
        receiver_config_provider: Optional[Callable[[], dict]] = None,
        peer_client: Optional[PeerClient] = None,
        compatibility_scorer: Optional[
            Callable[[Any, Any, Optional[str]], tuple[float, str]]
        ] = None,
        allow_private_initiator_urls: bool = False,
    ) -> None:
        if identity.role not in ("ap3_initiator", "ap3_receiver"):
            raise ValueError(f"unknown role: {identity.role}")
        self._id = identity

        # Precompute own AP3 params from the card (must already include AP3 ext).
        own_info = extract_peer_info(identity.card, agent_url=identity.self_url)

        self._core = _ProtocolCore(
            operation=operation,
            operation_type=identity.operation_type,
            private_key=identity.private_key,
            peer_client=peer_client or PeerClient(),
            own_info=own_info,
            self_url=identity.self_url,
            config_provider=receiver_config_provider,
            compatibility_scorer=compatibility_scorer,
            allow_private_initiator_urls=allow_private_initiator_urls,
        )

    async def run_intent(
        self,
        *,
        peer_url: str,
        inputs: Any,
        expiry_hours: int = DEFAULT_INTENT_EXPIRY_HOURS,
    ) -> PrivacyResultDirective:
        if self._id.role != "ap3_initiator":
            raise RuntimeError("run_intent() is only valid for initiators")
        return await self._core.run_intent(
            peer_url=peer_url, inputs=inputs, expiry_hours=expiry_hours
        )

    async def handle_envelope(self, envelope: ProtocolEnvelope) -> Optional[ProtocolEnvelope]:
        if self._id.role != "ap3_receiver":
            logger.warning("initiator received inbound envelope; dropping")
            return None
        return await self._core.handle_envelope(envelope)


def ensure_ap3_extension_present(card: AgentCard) -> AP3ExtensionParameters:
    """Return AP3ExtensionParameters from a card, or raise with a clear message."""
    for ext in card.capabilities.extensions or []:
        if ext.uri != AP3_EXTENSION_URI:
            continue
        params = MessageToDict(ext.params)
        return AP3ExtensionParameters.model_validate(
            {
                "roles": params.get("roles", []),
                "supported_operations": params.get("supported_operations", []),
                "commitments": params.get("commitments", []),
            }
        )
    raise ValueError("AgentCard has no AP3 extension; call attach_ap3_extension() first")
