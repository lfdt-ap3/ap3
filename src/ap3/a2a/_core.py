"""Shared AP3 protocol core — receiver dispatch + initiator run loop.

`PrivacyAgent` (full HTTP server) and `AP3Middleware` (drop-in for an
existing A2A server) both speak the same wire protocol. Originally each
class carried its own copy of the logic, which meant a security fix had
to land twice and could drift between them. This module is the single
implementation; both wrappers construct one `_ProtocolCore` and delegate.

Private — not part of the public API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ap3.a2a.card import normalize_url
from ap3.a2a.client import PeerClient, PeerInfo
from ap3.a2a._url_safety import UnsafeInitiatorURL, assert_safe_initiator_url
from ap3.a2a.wire import AP3_WIRE_VERSION, ProtocolEnvelope
from ap3.core.operation import Operation
from ap3.services.compatibility import CommitmentCompatibilityChecker
from ap3.signing.canonical import canonical_json_bytes
from ap3.types import (
    OperationProofs,
    PrivacyError,
    PrivacyIntentDirective,
    PrivacyProtocolError,
    PrivacyResultDirective,
    ResultData,
)

logger = logging.getLogger(__name__)

DEFAULT_INTENT_EXPIRY_HOURS = 24
MAX_ROUNDS = 64
SUPPORTED_WIRE_VERSIONS = frozenset({AP3_WIRE_VERSION})


@dataclass
class _ReceiverSession:
    """Per-session metadata the receiver tracks between rounds.

    Stores the initiator's pubkey so that intents on subsequent envelopes
    can be verified to come from the same signer that opened the session —
    a peer cannot mid-session swap in an intent signed by a different key.
    """
    internal_sid: str
    initiator_pubkey: bytes
    initiator_url: str


class _ProtocolCore:
    """Shared receiver/initiator state machine for AP3.

    Holds the per-instance protocol state (replay cache, round dedupe cache,
    receiver session map) and the Ed25519 identity. Construction takes the
    minimum dependencies needed for both roles; the wrapper class decides
    which methods to expose.
    """

    def __init__(
        self,
        *,
        operation: Operation,
        operation_type: str,
        private_key: bytes,
        peer_client: PeerClient,
        own_info: PeerInfo,
        self_url: str,
        config_provider: Optional[Callable[[], dict]] = None,
        compatibility_scorer: Optional[
            Callable[[Any, Any, Optional[str]], tuple[float, str]]
        ] = None,
        allow_private_initiator_urls: bool = False,
    ) -> None:
        self._operation = operation
        self._operation_type = operation_type
        self._private_key = private_key
        self._peer_client = peer_client
        self._own_info = own_info
        # Normalize once so every subsequent participants check / signed
        # intent uses the same canonical form.
        self._self_url = normalize_url(self_url)
        self._config_provider = config_provider
        self._compatibility_scorer = compatibility_scorer
        self._allow_private_initiator_urls = allow_private_initiator_urls

        # Anti-replay cache for first-round intents (receiver-side).
        # key -> expires_at_utc
        self._intent_replay_cache: dict[str, datetime] = {}
        # Per-round idempotency cache (receiver-side) to handle retries.
        # key -> (expires_at_utc, reply_envelope_or_none)
        self._round_dedupe_cache: dict[str, tuple[datetime, Optional[ProtocolEnvelope]]] = {}
        # wire_sid -> receiver session metadata, for multi-round sessions.
        self._rx_sessions: dict[str, _ReceiverSession] = {}
        # wire_sid -> asyncio.Lock. Two concurrent envelopes for the same
        # session would otherwise race on the dedupe-cache check and the
        # receive/process state, allowing duplicate execution and
        # weakening the replay guard. Different wire_sids run in parallel.
        self._session_locks: dict[str, asyncio.Lock] = {}

    # ---- initiator -------------------------------------------------------

    async def run_intent(
        self,
        *,
        peer_url: str,
        inputs: Any,
        expiry_hours: int = DEFAULT_INTENT_EXPIRY_HOURS,
    ) -> PrivacyResultDirective:
        """Full initiator round-trip against one peer.

        Runs `operation.start` and then loops send→process→send until the
        Operation signals `done`. Works for any number of rounds — PSI
        completes after one send/reply cycle; a protocol whose
        `on_process` alternates `done=False` with fresh `outgoing` runs
        as many rounds as it needs. Raises PrivacyError on peer refusal,
        missing reply, or the round cap.
        """
        peer = await self._peer_client.resolve_peer(peer_url)
        self._assert_compatible(peer)

        start = self._operation.start(role="initiator", inputs=inputs)
        internal_sid = start["session_id"]
        outgoing = start.get("outgoing")
        if start.get("done"):
            # No-network protocol: start() already produced a final result.
            return self.build_signed_result(
                session_id=internal_sid,
                operation_result=start.get("result") or {},
            )
        if outgoing is None:
            raise PrivacyProtocolError(
                PrivacyError(
                    error_code="NO_OUTGOING",
                    error_message="operation.start returned neither done nor outgoing",
                    operation_type=self._operation_type,
                )
            )

        wire_sid = outgoing.get("protocol_session") or internal_sid

        for round_num in range(MAX_ROUNDS):
            # Fresh, payload-bound intent per outbound envelope. Each intent's
            # payload_hash binds *this* envelope's payload, so any mid-session
            # swap is caught by `INTENT_PAYLOAD_MISMATCH` on the receiver.
            intent = self._build_signed_intent(
                session_id=wire_sid,
                peer_url=peer_url,
                payload=outgoing["message"],
                expiry_hours=expiry_hours,
            )
            envelope = ProtocolEnvelope(
                operation=self._operation.operation_id,
                phase=outgoing.get("phase", f"round{round_num}"),
                session_id=wire_sid,
                payload=outgoing["message"],
                privacy_intent=intent.model_dump(mode="json"),
            )
            reply = await self._peer_client.send_envelope(
                peer_url=peer_url,
                envelope=envelope,
                context_id=f"{self._operation.operation_id}_{wire_sid[:8]}",
            )
            if reply is None:
                raise PrivacyProtocolError(
                    PrivacyError(
                        error_code="NO_REPLY",
                        error_message="peer completed the call without returning a protocol envelope",
                        operation_type=self._operation_type,
                    )
                )
            if reply.error is not None:
                raise PrivacyProtocolError(PrivacyError.model_validate(reply.error))

            processed = self._operation.process(
                session_id=internal_sid,
                message={"phase": reply.phase, "message": reply.payload},
            )
            if processed.get("done"):
                return self.build_signed_result(
                    session_id=wire_sid,
                    operation_result=processed.get("result") or {},
                )
            outgoing = processed.get("outgoing")
            if outgoing is None:
                raise PrivacyProtocolError(
                    PrivacyError(
                        error_code="NO_OUTGOING",
                        error_message="operation.process returned neither done nor outgoing",
                        operation_type=self._operation_type,
                    )
                )

        raise PrivacyProtocolError(
            PrivacyError(
                error_code="ROUND_LIMIT",
                error_message=f"protocol exceeded {MAX_ROUNDS} rounds without completion",
                operation_type=self._operation_type,
            )
        )

    # ---- receiver --------------------------------------------------------

    async def handle_envelope(
        self, envelope: ProtocolEnvelope
    ) -> Optional[ProtocolEnvelope]:
        if envelope.operation != self._operation.operation_id:
            logger.warning(
                "rejecting envelope for unknown operation: %s", envelope.operation
            )
            return None
        return await self._handle_as_receiver(envelope)

    async def _handle_as_receiver(
        self, envelope: ProtocolEnvelope
    ) -> Optional[ProtocolEnvelope]:
        if envelope.ap3_wire_version not in SUPPORTED_WIRE_VERSIONS:
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="UNSUPPORTED_WIRE_VERSION",
                    error_message=(
                        f"unsupported ap3_wire_version {envelope.ap3_wire_version!r}; "
                        f"this receiver speaks {sorted(SUPPORTED_WIRE_VERSIONS)}"
                    ),
                    operation_type=self._operation_type,
                ),
            )

        wire_sid = envelope.session_id
        # Serialize all state-touching work for a given wire session id.
        # See `_session_locks` docstring above for why this is required.
        lock = self._session_locks.get(wire_sid)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[wire_sid] = lock
        try:
            async with lock:
                return await self._handle_as_receiver_locked(envelope, wire_sid)
        finally:
            # After the lock is released, drop the entry if nothing else is
            # waiting on it and the session has terminated. Prevents the
            # dict from growing unbounded across long-lived processes.
            if (
                not lock.locked()
                and wire_sid not in self._rx_sessions
                and self._session_locks.get(wire_sid) is lock
            ):
                self._session_locks.pop(wire_sid, None)

    async def _handle_as_receiver_locked(
        self, envelope: ProtocolEnvelope, wire_sid: str
    ) -> Optional[ProtocolEnvelope]:
        # Per-round idempotency: if this exact inbound envelope has been
        # processed recently, return the same reply without re-running the
        # operation/FFI.
        self._sweep_round_dedupe_cache()
        round_key = self._round_dedupe_key(envelope)
        cached = self._round_dedupe_cache.get(round_key)
        if cached is not None:
            _, reply = cached
            return reply

        rx_session = self._rx_sessions.get(wire_sid)
        message = {
            "phase": envelope.phase,
            "protocol_session": wire_sid,
            "message": envelope.payload,
        }

        if rx_session is None:
            # First inbound for this wire session: open the session via
            # operation.receive after a full intent validation.
            opened = await self._open_receiver_session(envelope, wire_sid, message)
            if isinstance(opened, ProtocolEnvelope):
                return opened
            result = opened
        else:
            # Subsequent inbound: each intent-bearing envelope is re-validated
            # against the cached signer + payload. Envelopes without an intent
            # are accepted as-is (the operation may emit non-intent-bearing
            # phases; the framework does not require intent on every round).
            if envelope.privacy_intent is not None:
                refusal = self._validate_subsequent_intent(envelope, rx_session)
                if refusal is not None:
                    return refusal
            try:
                result = self._operation.process(
                    session_id=rx_session.internal_sid,
                    message=message,
                )
            except KeyError:
                logger.warning("receiver session expired for wire_sid=%s", wire_sid[:8])
                self._rx_sessions.pop(wire_sid, None)
                return self._refuse(
                    envelope,
                    PrivacyError(
                        error_code="SESSION_EXPIRED",
                        error_message="receiver session expired",
                        operation_type=self._operation_type,
                    ),
                )
            except Exception as exc:
                logger.exception(
                    "operation.process failed for wire_sid=%s", wire_sid[:8]
                )
                del exc
                self._rx_sessions.pop(wire_sid, None)
                return self._refuse(
                    envelope,
                    PrivacyError(
                        error_code="OPERATION_ERROR",
                        error_message="internal operation failure",
                        operation_type=self._operation_type,
                    ),
                )
            if result.get("done"):
                self._rx_sessions.pop(wire_sid, None)

        outgoing = result.get("outgoing")
        if outgoing is None:
            self._round_dedupe_cache[round_key] = (
                datetime.now(timezone.utc) + timedelta(minutes=30),
                None,
            )
            return None
        reply = ProtocolEnvelope(
            operation=self._operation.operation_id,
            phase=outgoing.get("phase", "reply"),
            session_id=wire_sid,
            payload=outgoing["message"],
        )
        self._round_dedupe_cache[round_key] = (
            datetime.now(timezone.utc) + timedelta(minutes=30),
            reply,
        )
        return reply

    # ---- helpers ---------------------------------------------------------

    def _refuse(
        self, request: ProtocolEnvelope, error: PrivacyError
    ) -> ProtocolEnvelope:
        # Payload is required by the envelope schema; receivers and initiators
        # must ignore it when `error` is present.
        return ProtocolEnvelope(
            operation=request.operation,
            phase="error",
            session_id=request.session_id,
            payload={},
            error=error.model_dump(mode="json"),
        )

    def _assert_compatible(self, peer: PeerInfo) -> None:
        if self._compatibility_scorer is None:
            score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
                self._own_info.ap3_params,
                peer.ap3_params,
                operation_type=self._operation_type,
            )
        else:
            score, explanation = self._compatibility_scorer(
                self._own_info.ap3_params,
                peer.ap3_params,
                self._operation_type,
            )
        if not CommitmentCompatibilityChecker.is_compatible_score(score):
            raise PrivacyProtocolError(
                PrivacyError(
                    error_code="INCOMPATIBLE_PEER",
                    error_message=f"peer refused: {explanation}",
                    operation_type=self._operation_type,
                )
            )

    async def _open_receiver_session(
        self,
        envelope: ProtocolEnvelope,
        wire_sid: str,
        message: dict,
    ) -> ProtocolEnvelope | dict:
        """Validate the session-opening intent + call operation.receive().

        Returns a refusal envelope on failure, or the operation result dict on
        success. On success, stores the per-session metadata in `_rx_sessions`.
        """
        if envelope.privacy_intent is None:
            logger.warning("first-round envelope missing privacy_intent")
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="MISSING_INTENT",
                    error_message="first-round envelope missing privacy_intent",
                    operation_type=self._operation_type,
                ),
            )

        parsed = self._parse_intent(envelope)
        if isinstance(parsed, ProtocolEnvelope):
            return parsed
        intent = parsed

        # Session-opening-only checks: participants pair, peer compatibility.
        # Pydantic already enforces exactly 2 participants at parse time; this
        # is the defense-in-depth backstop.
        if len(intent.participants) != 2:
            logger.warning("intent.participants is not a pair")
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INVALID_INTENT",
                    error_message="intent.participants must be exactly [initiator, receiver]",
                    operation_type=self._operation_type,
                ),
            )
        initiator_url, receiver_url = intent.participants
        if not initiator_url or not receiver_url:
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INVALID_INTENT",
                    error_message="intent participants contain an empty URL",
                    operation_type=self._operation_type,
                ),
            )
        if normalize_url(receiver_url) != self._self_url:
            logger.warning("intent not addressed to this receiver")
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="WRONG_RECEIVER",
                    error_message=(
                        "intent.participants[1] does not match this receiver "
                        f"(expected {self._self_url})"
                    ),
                    operation_type=self._operation_type,
                ),
            )

        # SSRF guard: `initiator_url` arrives unauthenticated. Block obvious
        # local/private/metadata targets *before* the card fetch — otherwise
        # an attacker can force this receiver to GET arbitrary internal URLs
        # (cloud metadata, RFC1918 admin endpoints) prior to any signature
        # check. Dev/test loopback peers must opt in via
        # `allow_private_initiator_urls=True`.
        try:
            assert_safe_initiator_url(
                initiator_url,
                allow_private=self._allow_private_initiator_urls,
            )
        except UnsafeInitiatorURL as exc:
            logger.warning("rejecting unsafe initiator_url: %s", exc)
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INVALID_INITIATOR_URL",
                    error_message=str(exc),
                    operation_type=self._operation_type,
                ),
            )

        # Resolve peer (with one card-refresh on signature failure to handle
        # legitimate key rotation in dev).
        peer = await self._peer_client.resolve_peer(initiator_url)
        if not intent.verify_signature(peer.public_key):
            peer = await self._peer_client.resolve_peer(initiator_url, force_refresh=True)
            if not intent.verify_signature(peer.public_key):
                logger.warning("intent signature invalid")
                return self._refuse(
                    envelope,
                    PrivacyError(
                        error_code="BAD_SIGNATURE",
                        error_message="intent signature invalid",
                        operation_type=self._operation_type,
                    ),
                )

        # Shape-level checks + payload binding + replay.
        refusal = self._check_intent_consistency(envelope, intent, peer.public_key)
        if refusal is not None:
            return refusal

        # Compatibility check is session-level — runs once at open time.
        try:
            self._assert_compatible(peer)
        except PrivacyProtocolError as e:
            return self._refuse(envelope, e.error)

        config = self._config_provider() if self._config_provider else {}
        try:
            result = self._operation.receive(
                role="receiver",
                message=message,
                config=config,
                session_id=wire_sid,
            )
        except Exception as exc:
            logger.exception("operation.receive failed for wire_sid=%s", wire_sid[:8])
            del exc
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="OPERATION_ERROR",
                    error_message="internal operation failure",
                    operation_type=self._operation_type,
                ),
            )
        if not result.get("done"):
            self._rx_sessions[wire_sid] = _ReceiverSession(
                internal_sid=result["session_id"],
                initiator_pubkey=peer.public_key,
                initiator_url=initiator_url,
            )
        return result

    def _validate_subsequent_intent(
        self,
        envelope: ProtocolEnvelope,
        rx_session: _ReceiverSession,
    ) -> Optional[ProtocolEnvelope]:
        """Validate an intent on a non-opening envelope.

        Same signer as the session opener (pinned at open time), same
        ap3_session_id, payload_hash binds *this* envelope's payload, and the
        intent has not been replayed. Returns a refusal envelope or None.
        """
        parsed = self._parse_intent(envelope)
        if isinstance(parsed, ProtocolEnvelope):
            return parsed
        intent = parsed

        # Cross-envelope signer pinning: the intent must be signed by the same
        # key that opened the session. Defends against an attacker mid-session
        # presenting an intent signed by a different (also-valid) key.
        if not intent.verify_signature(rx_session.initiator_pubkey):
            logger.warning("subsequent intent signature does not match session signer")
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="BAD_SIGNATURE",
                    error_message="intent signature does not match session signer",
                    operation_type=self._operation_type,
                ),
            )

        return self._check_intent_consistency(
            envelope, intent, rx_session.initiator_pubkey
        )

    def _parse_intent(
        self, envelope: ProtocolEnvelope
    ) -> PrivacyIntentDirective | ProtocolEnvelope:
        """Parse the intent dict on `envelope` into a typed directive.

        Returns the directive on success or a refusal envelope on failure.
        """
        try:
            return PrivacyIntentDirective.model_validate(envelope.privacy_intent)
        except Exception as exc:
            logger.warning("intent payload failed validation: %s", exc)
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INVALID_INTENT",
                    error_message="intent payload failed validation",
                    operation_type=self._operation_type,
                ),
            )

    def _check_intent_consistency(
        self,
        envelope: ProtocolEnvelope,
        intent: PrivacyIntentDirective,
        initiator_pubkey: bytes,
    ) -> Optional[ProtocolEnvelope]:
        """Common per-intent checks: session match, op-type, payload binding,
        validate_directive, replay. Returns refusal or None."""
        if intent.ap3_session_id != envelope.session_id:
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INTENT_SESSION_MISMATCH",
                    error_message="intent.ap3_session_id does not match envelope.session_id",
                    operation_type=self._operation_type,
                ),
            )
        if intent.operation_type != self._operation_type:
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INTENT_OPERATION_MISMATCH",
                    error_message=(
                        f"intent.operation_type={intent.operation_type!r} does not match "
                        f"receiver's operation_type={self._operation_type!r}"
                    ),
                    operation_type=self._operation_type,
                ),
            )
        ok, err = intent.validate_directive()
        if not ok:
            logger.warning("intent rejected: %s", err)
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INTENT_REJECTED",
                    error_message=err or "intent rejected",
                    operation_type=self._operation_type,
                ),
            )
        expected = self._hash_payload(envelope.payload)
        if intent.payload_hash != expected:
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="INTENT_PAYLOAD_MISMATCH",
                    error_message="intent.payload_hash does not match envelope payload",
                    operation_type=self._operation_type,
                ),
            )
        # Per-intent replay (each intent has its own replay-cache entry,
        # keyed on intent_id+nonce+payload_hash so legitimate per-round
        # intents in the same session don't collide).
        self._sweep_intent_replay_cache()
        replay_key = self._intent_replay_key(
            initiator_pubkey=initiator_pubkey,
            session_id=envelope.session_id,
            intent_id=intent.intent_directive_id,
            nonce=intent.nonce,
            payload_hash=intent.payload_hash,
        )
        if replay_key in self._intent_replay_cache:
            return self._refuse(
                envelope,
                PrivacyError(
                    error_code="REPLAY",
                    error_message="replayed intent detected",
                    operation_type=self._operation_type,
                ),
            )
        self._intent_replay_cache[replay_key] = self._parse_expiry_utc(intent.expiry)
        return None

    def _build_signed_intent(
        self,
        *,
        session_id: str,
        peer_url: str,
        payload: Any,
        expiry_hours: int,
    ) -> PrivacyIntentDirective:
        expiry = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
        intent = PrivacyIntentDirective(
            ap3_session_id=session_id,
            intent_directive_id=str(uuid.uuid4()),
            operation_type=self._operation_type,
            # Both URLs go through `normalize_url` so a peer that compares
            # against its own self_url with different trailing-slash/case/port
            # gets a match on legitimate traffic.
            participants=[self._self_url, normalize_url(peer_url)],
            nonce=uuid.uuid4().hex,
            payload_hash=self._hash_payload(payload),
            expiry=expiry.isoformat(),
            signature=None,
        )
        intent.signature = intent.sign(self._private_key)
        return intent

    def _hash_payload(self, payload: Any) -> str:
        """Compute a stable SHA-256 hex digest of the on-wire payload."""
        if isinstance(payload, (str, bytes)):
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
        else:
            data = canonical_json_bytes(payload)
        return hashlib.sha256(data).hexdigest()

    def _parse_expiry_utc(self, expiry: str) -> datetime:
        try:
            dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    def _intent_replay_key(
        self,
        *,
        initiator_pubkey: bytes,
        session_id: str,
        intent_id: str,
        nonce: str,
        payload_hash: str,
    ) -> str:
        return "|".join(
            [initiator_pubkey.hex(), session_id, intent_id, nonce, payload_hash]
        )

    def _sweep_intent_replay_cache(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [k for k, exp in self._intent_replay_cache.items() if exp <= now]
        for k in expired:
            self._intent_replay_cache.pop(k, None)

    def _round_dedupe_key(self, envelope: ProtocolEnvelope) -> str:
        return "|".join(
            [
                envelope.operation,
                envelope.session_id,
                envelope.phase,
                self._hash_payload(envelope.payload),
            ]
        )

    def _sweep_round_dedupe_cache(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [k for k, (exp, _) in self._round_dedupe_cache.items() if exp <= now]
        for k in expired:
            self._round_dedupe_cache.pop(k, None)

    def build_signed_result(
        self,
        *,
        session_id: str,
        operation_result: dict,
    ) -> PrivacyResultDirective:
        canonical = canonical_json_bytes(operation_result)
        encoded = base64.b64encode(canonical).decode()
        result_hash = hashlib.sha256(canonical).hexdigest()
        result_data = ResultData(
            encoded_result=encoded,
            result_hash=result_hash,
            metadata={
                "operation": self._operation.operation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": canonical.decode("utf-8"),
                "proofs_note": "EXPERIMENTAL: proofs are placeholders (not cryptographic)",
            },
        )
        proofs = OperationProofs(
            correctness_proof=hashlib.sha256(
                f"correctness_{session_id}_{result_hash}".encode()
            ).hexdigest(),
            privacy_proof=hashlib.sha256(f"privacy_{session_id}".encode()).hexdigest(),
            verification_proof=hashlib.sha256(
                f"verification_{session_id}_{result_hash}".encode()
            ).hexdigest(),
        )
        directive = PrivacyResultDirective(
            ap3_session_id=session_id,
            result_directive_id=str(uuid.uuid4()),
            result_data=result_data,
            proofs=proofs,
            attestation="experimental_placeholders",
            signature=None,
        )
        directive.signature = directive.sign(self._private_key)
        return directive
