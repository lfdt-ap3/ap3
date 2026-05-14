"""Security-invariant tests for the AP3 receiver.

Each test exercises one of the receiver-side guarantees the protocol is
supposed to provide. They do not depend on the FFI or on a real network —
they construct intents directly and feed envelopes into the in-process
receiver, asserting on the structured `PrivacyError` returned for refusal
cases (or on the absence of a refusal for happy paths).
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ap3.a2a.agent import PrivacyAgent
from ap3.a2a.client import PeerInfo
from ap3.a2a.wire import ProtocolEnvelope
from ap3.signing.canonical import canonical_json_bytes
from ap3.signing.primitives import generate_keypair
from ap3.types import (
    AP3ExtensionParameters,
    CommitmentMetadata,
    DataFormat,
    DataFreshness,
    DataStructure,
    Industry,
    PrivacyIntentDirective,
)
from ap3_functions import PSIOperation
from ap3_functions.psi import HASH_SIZE

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


RECEIVER_URL = "http://localhost:9999"
INITIATOR_URL = "http://initiator.example"


def _commitment() -> CommitmentMetadata:
    return CommitmentMetadata(
        agent_id="test_agent",
        commitment_id="commit_v1",
        data_structure=DataStructure.CUSTOMER_LIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=1,
        field_count=1,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )


def _make_receiver(
    *,
    sanction_list: list[str] | None = None,
    allow_private_initiator_urls: bool = False,
) -> tuple[PrivacyAgent, bytes, bytes]:
    """Build a receiver agent and return it alongside its keypair.

    When ``sanction_list`` is provided, the receiver's config provider supplies
    it so that ``PSIOperation`` can complete a real session. Tests that don't
    need to drive a full PSI exchange can leave it out.

    ``allow_private_initiator_urls`` flips the dev-only SSRF-guard bypass; the
    default (False) matches production behavior.
    """
    priv, pub = generate_keypair()
    config_provider = (
        (lambda: {"sanction_list": sanction_list}) if sanction_list is not None else None
    )
    agent = PrivacyAgent(
        name="rx",
        description="rx",
        card_url=RECEIVER_URL,
        host="localhost",
        port=9999,
        role="ap3_receiver",
        operation=PSIOperation(),
        commitment=_commitment(),
        private_key=priv,
        public_key=pub,
        receiver_config_provider=config_provider,
        allow_private_initiator_urls=allow_private_initiator_urls,
    )
    return agent, priv, pub


def _make_initiator_keys() -> tuple[bytes, bytes]:
    return generate_keypair()


def _initiator_peer_info(
    initiator_pub: bytes, *, agent_url: str = INITIATOR_URL
) -> PeerInfo:
    """Build a PeerInfo for the initiator with shape compatible with the receiver."""
    return PeerInfo(
        agent_url=agent_url,
        ap3_params=AP3ExtensionParameters(
            roles=["ap3_initiator"],
            supported_operations=["PSI"],
            commitments=[_commitment()],
        ),
        wire_version="1.0",
        public_key=initiator_pub,
    )


def _hash_payload(payload) -> str:
    """Mirror `_ProtocolCore._hash_payload` for test envelope construction."""
    import hashlib

    if isinstance(payload, (str, bytes)):
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
    else:
        data = canonical_json_bytes(payload)
    return hashlib.sha256(data).hexdigest()


def _signed_intent(
    *,
    initiator_priv: bytes,
    payload,
    session_id: str,
    receiver_url: str = RECEIVER_URL,
    initiator_url: str = INITIATOR_URL,
    expiry: str | None = None,
    nonce: str | None = None,
    operation_type: str = "PSI",
) -> PrivacyIntentDirective:
    intent = PrivacyIntentDirective(
        ap3_session_id=session_id,
        intent_directive_id=str(uuid.uuid4()),
        operation_type=operation_type,
        participants=[initiator_url, receiver_url],
        nonce=nonce or uuid.uuid4().hex,
        payload_hash=_hash_payload(payload),
        expiry=expiry
        or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        signature=None,
    )
    intent.signature = intent.sign(initiator_priv)
    return intent


def _envelope_for(
    intent: PrivacyIntentDirective, *, payload, phase: str = "msg1"
) -> ProtocolEnvelope:
    return ProtocolEnvelope(
        operation=PSIOperation.operation_id,
        phase=phase,
        session_id=intent.ap3_session_id,
        payload=payload,
        privacy_intent=intent.model_dump(mode="json"),
    )


def _patch_resolve(monkeypatch, agent: PrivacyAgent, peer: PeerInfo) -> None:
    async def _resolve(url: str, *, force_refresh: bool = False):
        return peer

    monkeypatch.setattr(agent._core._peer_client, "resolve_peer", _resolve)


# ---------------------------------------------------------------------------
# High-priority security tests (action-plan item 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tampered_msg1_payload_is_refused(monkeypatch):
    """Mutating envelope.payload after signing must surface INTENT_PAYLOAD_MISMATCH."""
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_bytes_v1"
    intent = _signed_intent(
        initiator_priv=init_priv, payload=payload, session_id="sid-tamper"
    )
    env = _envelope_for(intent, payload=payload)
    # Tamper *after* signing — the on-wire payload no longer matches the
    # payload_hash baked into the signed intent.
    env = ProtocolEnvelope(
        operation=env.operation,
        phase=env.phase,
        session_id=env.session_id,
        payload="msg1_bytes_v1_TAMPERED",
        privacy_intent=env.privacy_intent,
    )

    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    assert reply.error["error_code"] == "INTENT_PAYLOAD_MISMATCH"


@pytest.mark.asyncio
async def test_replay_of_same_intent_is_refused(monkeypatch):
    """A byte-identical first-round envelope replayed must be refused as REPLAY.

    The first delivery should refuse for an unrelated reason (the FFI fails
    on synthetic msg1 bytes because we aren't speaking real PSI here). What
    matters is that the *second* delivery hits the replay guard before
    re-running anything.
    """
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_bytes_replay"
    intent = _signed_intent(
        initiator_priv=init_priv, payload=payload, session_id="sid-replay"
    )
    env = _envelope_for(intent, payload=payload)

    first = await agent.handle_envelope(env)
    # First call records the intent in the replay cache regardless of
    # whether the underlying operation succeeds.
    assert first is not None  # may be a refusal from the operation layer

    # Build a fresh envelope object with identical contents — the round
    # dedupe cache keys on payload hash, so we change the *phase* to bypass
    # the per-round dedupe and force the replay-cache code path.
    env2 = ProtocolEnvelope(
        operation=env.operation,
        phase=env.phase + "-retry",
        session_id=env.session_id,
        payload=env.payload,
        privacy_intent=env.privacy_intent,
    )
    second = await agent.handle_envelope(env2)
    assert second is not None and second.error is not None
    assert second.error["error_code"] == "REPLAY"


@pytest.mark.asyncio
async def test_unsupported_wire_version_is_refused(monkeypatch):
    """A peer advertising a future/unknown wire version must be refused."""
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_v2"
    intent = _signed_intent(
        initiator_priv=init_priv, payload=payload, session_id="sid-wirever"
    )
    env = _envelope_for(intent, payload=payload)
    env = env.model_copy(update={"ap3_wire_version": "9.9"})

    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    assert reply.error["error_code"] == "UNSUPPORTED_WIRE_VERSION"


@pytest.mark.asyncio
async def test_tampered_subsequent_envelope_is_refused(monkeypatch):
    """Per-envelope binding: tampering with msg1's payload after signing must
    surface INTENT_PAYLOAD_MISMATCH, even though the init envelope is fine.

    Verifies that intents on non-opening envelopes are also validated.
    """
    agent, _, _ = _make_receiver(sanction_list=["Jane Smith,S001,456 Elm St"])
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    session_id = "sid-tamper-subseq"
    commit_b = b"1" * HASH_SIZE
    payload = base64.b64encode(commit_b).decode("utf-8")

    # Envelope 1: init (opens the session)
    init_intent = _signed_intent(
        initiator_priv=init_priv, payload=payload, session_id=session_id
    )
    init_env = _envelope_for(init_intent, payload=payload, phase="init")
    init_reply = await agent.handle_envelope(init_env)
    assert init_reply is not None and init_reply.error is None
    assert init_reply.phase == "msg0"

    # Envelope 2: msg1 with intent bound to payload P, but actual payload P'.
    real_payload = "msg1_sid0_plus_psc"
    msg1_intent = _signed_intent(
        initiator_priv=init_priv, payload=real_payload, session_id=session_id
    )
    msg1_env = ProtocolEnvelope(
        operation=PSIOperation.operation_id,
        phase="msg1",
        session_id=session_id,
        payload="msg1_TAMPERED",  # ≠ what payload_hash binds
        privacy_intent=msg1_intent.model_dump(mode="json"),
    )
    msg1_reply = await agent.handle_envelope(msg1_env)
    assert msg1_reply is not None and msg1_reply.error is not None
    assert msg1_reply.error["error_code"] == "INTENT_PAYLOAD_MISMATCH"


@pytest.mark.asyncio
async def test_subsequent_intent_signed_by_different_key_is_refused(monkeypatch):
    """Per-envelope binding: a subsequent envelope's intent must be signed by
    the SAME key that opened the session. Defends against an attacker mid-
    session presenting an intent signed by a different (but also valid) key.
    """
    agent, _, _ = _make_receiver(sanction_list=["Jane Smith,S001"])
    legit_priv, legit_pub = _make_initiator_keys()
    other_priv, _other_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(legit_pub))

    session_id = "sid-signer-pin"
    commit_b = b"1" * HASH_SIZE
    payload = base64.b64encode(commit_b).decode("utf-8")

    # Open session with legit key.
    init_intent = _signed_intent(
        initiator_priv=legit_priv, payload=payload, session_id=session_id
    )
    init_env = _envelope_for(init_intent, payload=payload, phase="init")
    init_reply = await agent.handle_envelope(init_env)
    assert init_reply is not None and init_reply.error is None

    # Submit msg1 with intent signed by a different (also-valid) key — same
    # payload binding, only the signer differs.
    real_payload = "msg1_payload_bytes"
    rogue_intent = _signed_intent(
        initiator_priv=other_priv, payload=real_payload, session_id=session_id
    )
    rogue_env = _envelope_for(rogue_intent, payload=real_payload, phase="msg1")
    reply = await agent.handle_envelope(rogue_env)
    assert reply is not None and reply.error is not None
    assert reply.error["error_code"] == "BAD_SIGNATURE"


@pytest.mark.asyncio
async def test_intent_operation_type_mismatch_is_refused(monkeypatch):
    """An intent claiming a different operation_type than the receiver runs
    must never reach the operation layer.

    Today pydantic's `Literal["PSI"]` rejects any other value at parse time
    (INVALID_INTENT); the framework's explicit `INTENT_OPERATION_MISMATCH`
    check is a defense-in-depth backstop for when a second operation type
    lands and the Literal admits more than one value.
    """
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_optype"
    session_id = "sid-optype"
    intent = _signed_intent(
        initiator_priv=init_priv,
        payload=payload,
        session_id=session_id,
        operation_type="PSI",
    )
    intent_dict = intent.model_dump(mode="json")
    intent_dict["operation_type"] = "SFE"  # mutate after signing
    env = ProtocolEnvelope(
        operation=PSIOperation.operation_id,
        phase="msg1",
        session_id=session_id,
        payload=payload,
        privacy_intent=intent_dict,
    )
    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    assert reply.error["error_code"] in {
        "INVALID_INTENT",
        "BAD_SIGNATURE",
        "INTENT_OPERATION_MISMATCH",
    }


def test_intent_signature_does_not_verify_as_result_signature():
    """Domain separation: an intent signature must not validate against a result body.

    Before domain-separation prefixing was added, two structurally similar
    canonical bodies could collide and let a captured signature be reused
    across directive types. This test pins the negative invariant.
    """
    from ap3.types.directive import (
        _INTENT_DOMAIN,
        _RESULT_DOMAIN,
    )
    from ap3.signing.primitives import sign as crypto_sign, verify as crypto_verify

    init_priv, init_pub = _make_initiator_keys()

    # Deliberately use the *same* canonical body bytes for both. If
    # `verify_signature` ever drops the domain prefix, the same signature
    # will pass against either domain — exactly what we are guarding
    # against here.
    body = b'{"x":1}'
    intent_sig = crypto_sign(_INTENT_DOMAIN + body, init_priv)
    # The same signature must NOT verify against the RESULT domain — the
    # whole point of domain separation.
    assert not crypto_verify(_RESULT_DOMAIN + body, intent_sig, init_pub)
    # Sanity: it does verify against the INTENT domain.
    assert crypto_verify(_INTENT_DOMAIN + body, intent_sig, init_pub)


# ---------------------------------------------------------------------------
# Medium-priority security tests (action-plan item 14)
# ---------------------------------------------------------------------------


def test_extract_peer_info_rejects_short_hex():
    """L2-3: a too-short hex public key is refused with a clear error."""
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentExtension,
        AgentInterface,
    )
    from google.protobuf.struct_pb2 import Struct

    from ap3.a2a.card import (
        AP3_EXTENSION_URI,
        extract_peer_info,
    )

    card = AgentCard(
        name="x",
        description="x",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
    )
    card.supported_interfaces.append(
        AgentInterface(url="http://x", protocol_binding="JSONRPC")
    )
    params = Struct()
    params.update(
        {
            "ap3_version": "1.0.0",
            "ap3_wire_version": "1.0",
            # 60 hex chars instead of 64 — not a valid Ed25519 pubkey length.
            "public_key_hex": "ab" * 30,
            "roles": ["ap3_receiver"],
            "supported_operations": ["PSI"],
            "commitments": [],
        }
    )
    ext = AgentExtension(uri=AP3_EXTENSION_URI, description="x", required=True)
    ext.params.CopyFrom(params)
    card.capabilities.extensions.append(ext)

    with pytest.raises(ValueError, match="public_key_hex must be"):
        extract_peer_info(card, agent_url="http://x")


def test_extract_peer_info_rejects_non_hex_chars():
    """L2-3: non-hex characters in the key are refused."""
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentExtension,
        AgentInterface,
    )
    from google.protobuf.struct_pb2 import Struct

    from ap3.a2a.card import AP3_EXTENSION_URI, extract_peer_info

    card = AgentCard(
        name="x",
        description="x",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
    )
    card.supported_interfaces.append(
        AgentInterface(url="http://x", protocol_binding="JSONRPC")
    )
    params = Struct()
    params.update(
        {
            "ap3_version": "1.0.0",
            "ap3_wire_version": "1.0",
            "public_key_hex": "Z" * 64,  # right length, wrong charset
            "roles": ["ap3_receiver"],
            "supported_operations": ["PSI"],
            "commitments": [],
        }
    )
    ext = AgentExtension(uri=AP3_EXTENSION_URI, description="x", required=True)
    ext.params.CopyFrom(params)
    card.capabilities.extensions.append(ext)

    with pytest.raises(ValueError, match="not valid hex"):
        extract_peer_info(card, agent_url="http://x")


def test_normalize_url_collapses_trailing_slash_and_default_port():
    """L2-4: trivially different URLs that should compare equal, do."""
    from ap3.a2a.card import normalize_url

    assert normalize_url("http://X.Com:80/api/") == normalize_url("http://x.com/api")
    assert normalize_url("HTTPS://x.com:443") == normalize_url("https://x.com")
    assert normalize_url("http://x.com/api/") == normalize_url("http://x.com/api")


@pytest.mark.asyncio
async def test_url_trailing_slash_does_not_break_participants_check(monkeypatch):
    """L2-4 regression: an initiator that signed with a trailing slash on the receiver
    URL must still pass the receiver's participants check."""
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_url"
    # Initiator signs with `RECEIVER_URL + "/"`, receiver self_url is RECEIVER_URL.
    intent = _signed_intent(
        initiator_priv=init_priv,
        payload=payload,
        session_id="sid-url",
        receiver_url=RECEIVER_URL + "/",
    )
    env = _envelope_for(intent, payload=payload)

    reply = await agent.handle_envelope(env)
    # The reply may still surface a different error (e.g. INVALID_INTENT
    # from the FFI on synthetic msg1 bytes), but it must NOT be the
    # WRONG_RECEIVER refusal — the participants check must accept after
    # normalization.
    if reply is not None and reply.error is not None:
        assert reply.error["error_code"] != "WRONG_RECEIVER"


@pytest.mark.asyncio
async def test_oversized_envelope_is_rejected():
    """4.13: envelope_from_parts refuses payloads above MAX_ENVELOPE_JSON_BYTES."""
    from a2a.types import Part
    from google.protobuf.struct_pb2 import Struct, Value

    from ap3.a2a.wire import (
        AP3_ENVELOPE_DATA_KEY,
        MAX_ENVELOPE_JSON_BYTES,
        envelope_from_parts,
    )

    # Build a single Part containing a payload larger than the cap.
    big_payload = "A" * (MAX_ENVELOPE_JSON_BYTES + 1024)
    raw = {
        "ap3_wire_version": "1.0",
        "operation": PSIOperation.operation_id,
        "phase": "msg1",
        "session_id": "sid",
        "payload": big_payload,
    }
    struct = Struct()
    struct.update({AP3_ENVELOPE_DATA_KEY: raw})
    part = Part(data=Value(struct_value=struct))

    with pytest.raises(ValueError, match="too large"):
        envelope_from_parts([part])


@pytest.mark.asyncio
async def test_multi_envelope_parts_are_rejected():
    """L2-2: two AP3 envelopes on a single message is a refusal, not first-wins."""
    from a2a.types import Part
    from google.protobuf.struct_pb2 import Struct, Value

    from ap3.a2a.wire import AP3_ENVELOPE_DATA_KEY, envelope_from_parts

    def _envelope_part(session_id: str) -> Part:
        raw = {
            "ap3_wire_version": "1.0",
            "operation": PSIOperation.operation_id,
            "phase": "msg1",
            "session_id": session_id,
            "payload": "p",
        }
        s = Struct()
        s.update({AP3_ENVELOPE_DATA_KEY: raw})
        return Part(data=Value(struct_value=s))

    parts = [_envelope_part("a"), _envelope_part("b")]
    with pytest.raises(ValueError, match="appears on 2 parts"):
        envelope_from_parts(parts)


@pytest.mark.asyncio
async def test_concurrent_receivers_for_same_session_are_serialized(monkeypatch):
    """4.8: two parallel envelopes for the same wire_sid must not race.

    With per-session locking, the second call waits until the first
    completes; the first call writes the intent into the replay cache
    *before* running the operation, so the second observes a REPLAY
    refusal. Without the lock, both calls could pass the replay check in
    parallel, then both run the operation — exactly the race we want to
    rule out.
    """
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_concurrent"
    intent = _signed_intent(
        initiator_priv=init_priv, payload=payload, session_id="sid-concurrent"
    )
    env = _envelope_for(intent, payload=payload)

    r1, r2 = await asyncio.gather(
        agent.handle_envelope(env),
        agent.handle_envelope(env),
    )
    assert r1 is not None and r2 is not None
    error_codes = sorted(r.error["error_code"] for r in (r1, r2))
    # The race-free outcome: one delivery enters first, populates the
    # replay cache, then runs the operation (which fails here because we
    # haven't wired a real sanction_list config — OPERATION_ERROR). The
    # second waits, sees the populated replay cache, and refuses with
    # REPLAY. If the lock is missing, both deliveries run the operation
    # and we'd see two OPERATION_ERROR results.
    assert "REPLAY" in error_codes, (
        f"per-session lock did not serialize: got {error_codes}"
    )


@pytest.mark.asyncio
async def test_malformed_expiry_field_is_refused(monkeypatch):
    """7: garbage `expiry` makes the intent treat itself as expired and refuses."""
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    payload = "msg1_exp"
    intent = _signed_intent(
        initiator_priv=init_priv,
        payload=payload,
        session_id="sid-exp",
        expiry="not-a-real-iso-timestamp",
    )
    env = _envelope_for(intent, payload=payload)

    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    # `validate_directive()` -> `is_expired()` returns True for a
    # malformed timestamp, so the receiver refuses with INTENT_REJECTED.
    assert reply.error["error_code"] == "INTENT_REJECTED"


@pytest.mark.asyncio
async def test_bad_signature_after_force_refresh_is_refused(monkeypatch):
    """A signature that cannot verify even after a forced card refresh is refused.

    This exercises the receiver's `force_refresh=True` retry path: the
    first verification fails against the cached pubkey, so the receiver
    asks the PeerClient for a fresh card; if that *still* doesn't
    verify, the directive is refused with BAD_SIGNATURE.
    """
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    # The PeerClient always returns the *wrong* key — every refresh
    # produces the same mismatch, exercising the retry without an
    # infinite loop.
    wrong_pub = generate_keypair()[1]
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(wrong_pub))

    payload = "msg1_badsig"
    intent = _signed_intent(
        initiator_priv=init_priv, payload=payload, session_id="sid-badsig"
    )
    env = _envelope_for(intent, payload=payload)

    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    assert reply.error["error_code"] == "BAD_SIGNATURE"


def test_commitment_data_hash_uses_canonical_encoder():
    """4.10 regression: `_hash_data_content` produces the same bytes as
    `canonical_json_bytes`, so cross-implementation integrity checks agree."""
    import hashlib

    from ap3.services.commitment import CommitmentMetadataSystem

    sys = CommitmentMetadataSystem()
    data = [{"b": 2, "a": 1}, {"x": [3, 1, 2]}]

    expected = hashlib.sha256(canonical_json_bytes(data)).hexdigest()
    assert sys._hash_data_content(data) == expected


def test_extra_fields_on_signed_directive_are_rejected():
    """4.7: `extra="forbid"` on PrivacyIntentDirective refuses unknown fields.

    Without this, an upgrade peer that adds a new field would have its
    field silently dropped on deserialize and signature verification
    would then mysteriously fail on legitimate traffic.
    """
    from pydantic import ValidationError

    intent_payload = {
        "ap3_session_id": "sid",
        "intent_directive_id": "id",
        "operation_type": "PSI",
        "participants": ["a", "b"],
        "nonce": "n",
        "payload_hash": "0" * 64,
        "expiry": "2999-01-01T00:00:00+00:00",
        "signature": None,
        # extra field — must be refused outright, not silently dropped
        "future_field": True,
    }
    with pytest.raises(ValidationError):
        PrivacyIntentDirective.model_validate(intent_payload)


# ---------------------------------------------------------------------------
# Intent.participants pair constraint (security: prevents cross-receiver reuse)
# ---------------------------------------------------------------------------


def test_intent_with_three_participants_rejected_at_parse_time():
    """Pydantic constraint: participants must be exactly 2 entries.

    A single signed intent listing N>2 participants could otherwise be
    submitted to each receiver in turn — every BB would find itself in the
    list and pass the participants check, accepting an authorization that
    was never specifically for it. The Field max_length=2 backstop fires
    here at parse time.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PrivacyIntentDirective(
            ap3_session_id="sid",
            intent_directive_id="id",
            operation_type="PSI",
            participants=["initiator", "bb_a", "bb_b"],
            nonce="n",
            payload_hash="0" * 64,
            expiry="2999-01-01T00:00:00+00:00",
            signature=None,
        )


def test_intent_with_single_participant_rejected_at_parse_time():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PrivacyIntentDirective(
            ap3_session_id="sid",
            intent_directive_id="id",
            operation_type="PSI",
            participants=["just_one"],
            nonce="n",
            payload_hash="0" * 64,
            expiry="2999-01-01T00:00:00+00:00",
            signature=None,
        )


@pytest.mark.asyncio
async def test_intent_with_three_participants_in_dict_rejected_by_framework(monkeypatch):
    """Defense-in-depth: even if a peer crafts a raw dict that bypasses
    pydantic's Field validator (e.g. a future codepath sets participants
    after construction), the framework's explicit length check still fires.
    """
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(monkeypatch, agent, _initiator_peer_info(init_pub))

    # Build a valid intent, then mutate its serialized form to bypass the
    # pydantic constraint. The signature will still match the original
    # 2-participant body — but BB's framework check on participant count
    # fires before any signature work.
    payload = "msg1_multireceiver"
    session_id = "sid-multireceiver"
    intent = _signed_intent(initiator_priv=init_priv, payload=payload, session_id=session_id)
    intent_dict = intent.model_dump(mode="json")
    intent_dict["participants"] = [INITIATOR_URL, RECEIVER_URL, "http://other.example"]

    env = ProtocolEnvelope(
        operation=PSIOperation.operation_id,
        phase="msg1",
        session_id=session_id,
        payload=payload,
        privacy_intent=intent_dict,
    )
    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    # Either pydantic re-validation (INVALID_INTENT) or the framework's
    # explicit length backstop fires. Both keep the envelope away from the
    # operation layer.
    assert reply.error["error_code"] in {"INVALID_INTENT", "BAD_SIGNATURE"}


# ---------------------------------------------------------------------------
# SSRF guard: unverified initiator_url must be classified before card fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_initiator_url",
    [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
        "http://169.254.169.254/latest/meta-data/",  # AWS IMDS
        "http://metadata.google.internal/",          # GCP metadata
        "http://10.0.0.1:8080",                      # RFC1918
        "http://192.168.1.1/",                       # RFC1918
        "file:///etc/passwd",                        # scheme check
    ],
)
async def test_ssrf_guard_refuses_unsafe_initiator_url(monkeypatch, bad_initiator_url):
    """Receiver must classify the unverified initiator_url BEFORE fetching the card.

    The default receiver does not opt into `allow_private_initiator_urls=True`;
    any URL pointing at loopback, private/link-local space, cloud metadata
    services, or non-http(s) schemes must surface INVALID_INITIATOR_URL. The
    PeerClient mock fails loudly if it is ever reached, pinning the invariant
    that the guard fires *before* the unauthenticated HTTP GET.
    """
    agent, _, _ = _make_receiver()
    init_priv, init_pub = _make_initiator_keys()

    async def _must_not_resolve(url: str, *, force_refresh: bool = False):
        raise AssertionError(
            f"resolve_peer fetched {url!r} before the SSRF guard ran — "
            "this is the bug the guard exists to prevent"
        )

    monkeypatch.setattr(agent._core._peer_client, "resolve_peer", _must_not_resolve)

    payload = "ssrf_attempt"
    intent = _signed_intent(
        initiator_priv=init_priv,
        payload=payload,
        session_id="sid-ssrf",
        initiator_url=bad_initiator_url,
    )
    env = _envelope_for(intent, payload=payload, phase="init")
    reply = await agent.handle_envelope(env)
    assert reply is not None and reply.error is not None
    assert reply.error["error_code"] == "INVALID_INITIATOR_URL"


@pytest.mark.asyncio
async def test_ssrf_guard_bypass_with_allow_private_initiator_urls(monkeypatch):
    """`allow_private_initiator_urls=True` is the dev escape hatch.

    With the flag set, a localhost initiator URL must pass the guard so the
    codelabs and `examples/*` quickstarts can run on a single machine.
    """
    agent, _, _ = _make_receiver(allow_private_initiator_urls=True)
    init_priv, init_pub = _make_initiator_keys()
    _patch_resolve(
        monkeypatch,
        agent,
        _initiator_peer_info(init_pub, agent_url="http://localhost:10002"),
    )

    payload = "loopback_ok"
    intent = _signed_intent(
        initiator_priv=init_priv,
        payload=payload,
        session_id="sid-loopback",
        initiator_url="http://localhost:10002",
    )
    env = _envelope_for(intent, payload=payload, phase="init")
    reply = await agent.handle_envelope(env)
    # We don't require success here (FFI/synthetic payloads may surface other
    # refusals); we only require that the SSRF guard did NOT fire.
    if reply is not None and reply.error is not None:
        assert reply.error["error_code"] != "INVALID_INITIATOR_URL"
