"""Outbound transport to a remote AP3 agent over A2A.

The PeerClient is owned by a single PrivacyAgent and caches resolved peer
cards. It is the *only* module in `ap3.a2a` that talks to the network, so
swapping transports (A2A/JSONRPC today, gRPC tomorrow) means rewriting
this file and nothing else.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import AsyncIterator, Callable, Optional
import contextlib

import httpx

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Role, SendMessageRequest

from ap3.a2a.card import PeerInfo, extract_peer_info
from ap3.a2a.wire import ProtocolEnvelope, envelope_from_parts, envelope_to_part

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

# Minimum interval between forced card refreshes for the same peer. Without
# this, an attacker that floods a receiver with bad-signature envelopes
# would force one HTTP card fetch per envelope. Set short enough that a
# legitimate key rotation is picked up in seconds, long enough that flood
# traffic doesn't translate into amplified outbound HTTP load.
_DEFAULT_FORCE_REFRESH_INTERVAL_S = 5.0


class PeerClient:
    """Lazy A2A client with an in-memory peer card + PeerInfo cache.

    Cache is per-process and never persisted: if a peer rotates its
    AP3 public key, restart the agent. That is intentional — we do not
    want silent trust continuation across key rotation.
    """

    def __init__(
        self,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        *,
        httpx_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
        force_refresh_interval_s: float = _DEFAULT_FORCE_REFRESH_INTERVAL_S,
    ) -> None:
        self._timeout = timeout
        self._httpx_client_factory = httpx_client_factory
        self._cards: dict[str, AgentCard] = {}
        self._peers: dict[str, PeerInfo] = {}
        self._force_refresh_interval_s = force_refresh_interval_s
        # Per-peer monotonic timestamp of the last successful forced refresh.
        self._last_force_refresh: dict[str, float] = {}

    @contextlib.asynccontextmanager
    async def _http(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._httpx_client_factory is None:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                yield http
            return
        http = self._httpx_client_factory()
        try:
            yield http
        finally:
            await http.aclose()

    async def resolve_peer(self, peer_url: str, *, force_refresh: bool = False) -> PeerInfo:
        """Fetch + cache a peer's AgentCard and return its AP3 PeerInfo.

        Raises ValueError if the peer has no AP3 extension. Network errors
        propagate as httpx exceptions — the caller decides whether to
        retry or surface a PrivacyError to its own caller.

        `force_refresh=True` is rate-limited per peer (see
        `force_refresh_interval_s`): consecutive calls within the window
        return the cached entry instead of round-tripping. This kills the
        DoS where a flood of bad-signature envelopes triggers a card fetch
        per envelope, while still letting legitimate key rotation be
        picked up within seconds.
        """
        if force_refresh:
            now = time.monotonic()
            last = self._last_force_refresh.get(peer_url, 0.0)
            if (now - last) < self._force_refresh_interval_s:
                cached = self._peers.get(peer_url)
                if cached is not None:
                    return cached
            self._last_force_refresh[peer_url] = now
        else:
            cached = self._peers.get(peer_url)
            if cached is not None:
                return cached

        card = await self._fetch_card(peer_url, force_refresh=force_refresh)
        info = extract_peer_info(card, agent_url=peer_url)
        self._peers[peer_url] = info
        return info

    async def send_envelope(
        self,
        *,
        peer_url: str,
        envelope: ProtocolEnvelope,
        context_id: Optional[str] = None,
    ) -> Optional[ProtocolEnvelope]:
        """Ship one ProtocolEnvelope to a peer, return its reply if any.

        The reply rides back as the A2A task artifact — the peer's
        executor packs its outgoing envelope into `Part.data` and the
        client pulls it off the final task's artifacts. Returns None if
        the peer completed the task without emitting a reply envelope
        (that is the contract for a one-shot phase with no next round).
        """
        card = await self._fetch_card(peer_url)
        async with self._http() as http:
            client = ClientFactory(
                config=ClientConfig(httpx_client=http)
            ).create(card=card)

            message = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()))
            if context_id is not None:
                message.context_id = context_id
            message.parts.append(envelope_to_part(envelope))
            request = SendMessageRequest(message=message)

            last_task = None
            reply: Optional[ProtocolEnvelope] = None
            async for event in client.send_message(request):
                which = event.WhichOneof("payload")
                if which == "task":
                    last_task = event.task
                elif which == "artifact_update":
                    # Streaming path: artifacts arrive as incremental updates.
                    artifact = event.artifact_update.artifact
                    candidate = envelope_from_parts(list(artifact.parts))
                    if candidate is not None:
                        reply = candidate
                elif which == "message":
                    # Some servers may return a one-shot message. We don't expect
                    # protocol envelopes here, but tolerate it.
                    candidate = envelope_from_parts(list(event.message.parts))
                    if candidate is not None:
                        reply = candidate

        logger.debug(
            "Sent AP3 envelope operation=%s phase=%s session=%s to %s",
            envelope.operation,
            envelope.phase,
            envelope.session_id[:8],
            peer_url,
        )

        if reply is not None:
            return reply
        if last_task is None:
            return None
        for artifact in last_task.artifacts:
            candidate = envelope_from_parts(list(artifact.parts))
            if candidate is not None:
                return candidate
        return None

    async def _fetch_card(self, peer_url: str, *, force_refresh: bool = False) -> AgentCard:
        if not force_refresh:
            cached = self._cards.get(peer_url)
            if cached is not None:
                return cached
        async with self._http() as http:
            resolver = A2ACardResolver(httpx_client=http, base_url=peer_url)
            card = await resolver.get_agent_card()
        self._cards[peer_url] = card
        return card
