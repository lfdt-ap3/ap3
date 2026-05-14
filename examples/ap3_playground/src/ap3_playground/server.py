from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from a2a.types import AgentCapabilities, AgentCard, AgentInterface

from ap3.a2a import PrivacyAgent
from ap3.a2a.card import AP3_EXTENSION_URI, normalize_url
from ap3.a2a.wire import ProtocolEnvelope
from ap3.a2a.client import PeerClient
from ap3.signing.canonical import canonical_json_bytes
from ap3.signing.primitives import generate_keypair
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
from ap3.types.directive import PrivacyIntentDirective
from ap3_functions import PSIOperation
from ap3.services.compatibility import CommitmentCompatibilityChecker
from ap3.a2a.card import build_privacy_agent_card
from ap3.services.commitment import CommitmentMetadataSystem
from ap3 import __version__ as _AP3_VERSION
import asyncio
import contextlib
import traceback
import contextvars
from google.protobuf.json_format import MessageToDict

RECEIVER_DATASET = ["Jane Smith,S001,456 Elm St", "Bob Brown,S002,789 Oak Ave"]
DEFAULT_INTENT_EXPIRY_HOURS = 24

_walk_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("walk_id", default=None)


@dataclass
class WalkState:
    walk_id: str
    created_at: float
    last_used: float
    lab_key: Optional[str] = None
    wire_sid: Optional[str] = None
    internal_sid: Optional[str] = None
    intent_payload: Optional[dict[str, Any]] = None
    msg1_outgoing: Optional[dict[str, Any]] = None
    reply: Optional[ProtocolEnvelope] = None
    trace_base: Optional[Trace] = None
    http_capture: list[dict[str, Any]] = None  # type: ignore[assignment]
    lock: asyncio.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.http_capture is None:
            self.http_capture = []
        if self.lock is None:
            self.lock = asyncio.Lock()


_WALKS: dict[str, WalkState] = {}
_WALKS_TTL_S = 30 * 60


def _sweep_walks() -> None:
    now = time.time()
    expired = [k for k, w in _WALKS.items() if (now - w.last_used) > _WALKS_TTL_S]
    for k in expired:
        _WALKS.pop(k, None)


def _get_walk(walk_id: str) -> WalkState:
    _sweep_walks()
    w = _WALKS.get(walk_id)
    if w is None:
        raise ValueError("invalid walk_id (expired or unknown)")
    w.last_used = time.time()
    return w

SCENARIOS = Literal[
    "psi",
    "compat_mismatch",
    "tamper_session_id",
    "tamper_participants",
    "replay",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _card(url: str, *, name: str) -> AgentCard:
    c = AgentCard(
        name=name,
        description="AP3 Playground agent",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
    )
    c.supported_interfaces.append(AgentInterface(url=url, protocol_binding="JSONRPC"))
    return c


def _one_commitment(*, agent_id: str, commitment_id: str, structure: DataStructure) -> CommitmentMetadata:
    return CommitmentMetadata(
        agent_id=agent_id,
        commitment_id=commitment_id,
        data_structure=structure,
        data_format=DataFormat.STRUCTURED,
        entry_count=1,
        field_count=1,
        estimated_size_mb=0.001,
        last_updated=_now_iso(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )


def _sha256_hex(payload: Any) -> str:
    if isinstance(payload, bytes):
        b = payload
    elif isinstance(payload, str):
        b = payload.encode("utf-8")
    else:
        b = canonical_json_bytes(payload)
    return hashlib.sha256(b).hexdigest()

def _hash_payload(payload: Any) -> str:
    # Keep consistent with `AP3Middleware._hash_payload()`.
    if isinstance(payload, (str, bytes)):
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
    else:
        data = canonical_json_bytes(payload)
    return hashlib.sha256(data).hexdigest()

def _receiver_checks_from_intent(
    *,
    envelope: ProtocolEnvelope,
    receiver_url: str,
    initiator_public_key: bytes,
) -> list[tuple[str, bool, dict[str, Any]]]:
    """Mirror the receiver-side AP3 checks for the first round."""
    if envelope.privacy_intent is None:
        return [("rx.check.missing_intent", False, {"note": "first-round envelope missing privacy_intent"})]

    intent_dict = envelope.privacy_intent
    intent = PrivacyIntentDirective.model_validate(intent_dict)

    checks: list[tuple[str, bool, dict[str, Any]]] = []

    sid_ok = (intent.ap3_session_id == envelope.session_id)
    checks.append(
        (
            "rx.check.session_binding",
            sid_ok,
            {"intent.ap3_session_id": intent.ap3_session_id, "envelope.session_id": envelope.session_id},
        )
    )

    participants = list(intent.participants or [])
    # Mirror the receiver's normalize-then-compare logic so the audit trace
    # stays faithful when users tinker with URLs (trailing slash, default
    # port, scheme/host casing). The real check happens in
    # `ap3.a2a._core._ProtocolCore._handle_as_receiver_locked`.
    expected_norm = normalize_url(receiver_url)
    recv_ok = expected_norm in {normalize_url(p) for p in participants[1:]}
    checks.append(
        (
            "rx.check.participants",
            recv_ok,
            {
                "participants": participants,
                "expected_receiver": receiver_url,
                "expected_receiver_normalized": expected_norm,
            },
        )
    )

    sig_ok = intent.verify_signature(initiator_public_key)
    checks.append(("rx.check.signature", sig_ok, {"initiator_pubkey_hex": initiator_public_key.hex()}))

    ok, err = intent.validate_directive()
    checks.append(("rx.check.directive_validate", bool(ok), {"error": err}))

    expected = _hash_payload(envelope.payload)
    payload_ok = (intent.payload_hash == expected)
    checks.append(
        (
            "rx.check.payload_hash",
            payload_ok,
            {"intent.payload_hash": intent.payload_hash, "expected_from_payload": expected},
        )
    )

    # Replay check depends on receiver-side cache state; we surface the computed key for observability.
    checks.append(
        (
            "rx.check.replay_key",
            True,
            {
                "replay_key": "|".join(
                    [
                        initiator_public_key.hex(),
                        envelope.session_id,
                        intent.intent_directive_id,
                        intent.nonce,
                        intent.payload_hash,
                    ]
                )
            },
        )
    )
    return checks


class AuditEvent(TypedDict):
    ts_ms: int
    name: str
    ok: bool
    details: dict[str, Any]


class Trace(TypedDict):
    scenario: str
    request: dict[str, Any]
    a2a_http: list[dict[str, Any]]
    agent_cards: dict[str, Any]
    psi_data: dict[str, Any]
    envelopes: list[dict[str, Any]]
    directives: dict[str, Any]
    audit: list[AuditEvent]
    logs: list[dict[str, Any]]
    result: dict[str, Any]


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_static(name: str) -> str:
    p = STATIC_DIR / name
    return p.read_text(encoding="utf-8")


class AgentLabConfig(TypedDict, total=False):
    role: str
    supported_operations: list[str]
    data_structure: str
    data_format: str
    data_freshness: str
    industry: str


def _commitment_from_lab(*, agent_id: str, cfg: AgentLabConfig) -> CommitmentMetadata:
    ds = DataStructure(cfg.get("data_structure") or DataStructure.CUSTOMER_LIST.value)
    df = DataFormat(cfg.get("data_format") or DataFormat.STRUCTURED.value)
    fr = DataFreshness(cfg.get("data_freshness") or DataFreshness.REAL_TIME.value)
    ind = Industry(cfg.get("industry") or Industry.FINANCE.value)
    return CommitmentMetadata(
        agent_id=agent_id,
        commitment_id=f"lab-{agent_id}",
        data_structure=ds,
        data_format=df,
        entry_count=1,
        field_count=1,
        estimated_size_mb=0.001,
        last_updated=_now_iso(),
        data_freshness=fr,
        industry=ind,
    )


def _apply_supported_ops_to_card(card: AgentCard, ops: list[str]) -> None:
    for ext in (card.capabilities.extensions or []):
        if ext.uri != AP3_EXTENSION_URI:
            continue
        ext.params.update({"supported_operations": list(ops)})
        return


def _card_to_dict(card: AgentCard) -> dict[str, Any]:
    # AgentCard is a protobuf message. It supports JSON round-trip via dict.
    # We keep it minimal and stable for the demo UI.
    exts = []
    for ext in (card.capabilities.extensions or []):
        params = None
        if ext.params is not None:
            # ext.params is google.protobuf.Struct; convert to JSON-like dict.
            params = MessageToDict(ext.params, preserving_proto_field_name=True)
        exts.append(
            {
                "uri": ext.uri,
                "description": ext.description,
                "required": bool(ext.required),
                "params": params,
            }
        )
    ifaces = [{"url": i.url, "protocol_binding": i.protocol_binding} for i in card.supported_interfaces]
    return {
        "name": card.name,
        "description": card.description,
        "version": card.version,
        "supported_interfaces": ifaces,
        "capabilities": {
            "streaming": bool(card.capabilities.streaming),
            "extensions": exts,
        },
    }


def _ap3_ext_decoded(card: AgentCard) -> Optional[dict[str, Any]]:
    for ext in (card.capabilities.extensions or []):
        if ext.uri != AP3_EXTENSION_URI:
            continue
        if ext.params is None:
            return None
        # ext.params is a google.protobuf Struct; convert to JSON-like dict.
        return MessageToDict(ext.params, preserving_proto_field_name=True)
    return None


def _envelope_to_dict(env: ProtocolEnvelope) -> dict[str, Any]:
    payload_hash = _sha256_hex(env.payload)
    payload_bytes = (
        env.payload if isinstance(env.payload, (bytes, bytearray)) else json.dumps(env.payload, default=str).encode("utf-8")
    )
    return {
        "operation": env.operation,
        "phase": env.phase,
        "session_id": env.session_id,
        "payload_preview": (env.payload[:160] + "…") if isinstance(env.payload, str) and len(env.payload) > 160 else env.payload,
        "payload_sha256": payload_hash,
        "payload_bytes": len(payload_bytes),
        "privacy_intent_present": env.privacy_intent is not None,
        "error": env.error,
    }


def _canonical_and_sig(directive_dict: dict[str, Any]) -> dict[str, Any]:
    sig_b64 = directive_dict.get("signature")
    unsigned = dict(directive_dict)
    unsigned.pop("signature", None)
    canonical = canonical_json_bytes(unsigned)
    out: dict[str, Any] = {
        "canonical_json": canonical.decode("utf-8"),
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    if sig_b64:
        try:
            out["signature_b64"] = sig_b64
            out["signature_bytes"] = len(base64.b64decode(sig_b64))
        except Exception:
            out["signature_b64"] = sig_b64
            out["signature_bytes"] = None
    return out


def _log(logs: list[dict[str, Any]], *, level: str, event: str, **fields: Any) -> None:
    logs.append({"ts": _now_iso(), "level": level, "event": event, **fields})


async def _run_scenario(scenario: SCENARIOS) -> Trace:
    t0 = time.time()
    audit: list[AuditEvent] = []
    logs: list[dict[str, Any]] = []
    envelopes: list[dict[str, Any]] = []
    captured_intent: Optional[dict[str, Any]] = None

    def audit_step(name: str, ok: bool, **details: Any) -> None:
        audit.append(
            {
                "ts_ms": int((time.time() - t0) * 1000),
                "name": name,
                "ok": ok,
                "details": details,
            }
        )

    # --- use long-lived PrivacyAgent servers (initiator + receiver)
    lab = {
        "initiator": getattr(_run_scenario, "_initiator_cfg", {}) or {},  # type: ignore[attr-defined]
        "receiver": getattr(_run_scenario, "_receiver_cfg", {}) or {},  # type: ignore[attr-defined]
    }
    initiator_agent, receiver_agent, http_capture = await _ensure_agents(lab)
    initiator_url = "http://127.0.0.1:18082"
    receiver_url = "http://127.0.0.1:18083"
    attacks: dict[str, Any] = getattr(_run_scenario, "_attacks", {})  # type: ignore[attr-defined]

    # Compatibility mismatch demo: break initiator's advertised ops on its AgentCard.
    if scenario == "compat_mismatch" or attacks.get("compat_mismatch"):
        audit_step(
            "tamper.compatibility",
            True,
            note="initiator card advertises unsupported operation PIR",
        )
        for ext in (initiator_agent._card.capabilities.extensions or []):  # type: ignore[attr-defined]
            if ext.uri == AP3_EXTENSION_URI:
                ext.params.update({"supported_operations": ["PIR"]})

    # Tamper scenarios: we implement by patching PeerClient.send_envelope to mutate the outbound envelope.
    original_send = initiator_agent._core._peer_client.send_envelope  # type: ignore[attr-defined]

    async def _send_envelope_tampered(
        *,
        peer_url: str,
        envelope: ProtocolEnvelope,
        context_id: Optional[str] = None,
    ):
        env = envelope
        if scenario == "tamper_session_id" or attacks.get("tamper_session_id"):
            env = ProtocolEnvelope(
                operation=envelope.operation,
                phase=envelope.phase,
                session_id="tampered-" + envelope.session_id,
                payload=envelope.payload,
                privacy_intent=envelope.privacy_intent,
            )
            audit_step("tamper.session_id", True, note="modified envelope.session_id")
        if (scenario == "tamper_participants" or attacks.get("tamper_participants")) and env.privacy_intent is not None:
            pi = dict(env.privacy_intent)
            pi["participants"] = [initiator_url, "http://someone-else.example"]
            env = ProtocolEnvelope(
                operation=env.operation,
                phase=env.phase,
                session_id=env.session_id,
                payload=env.payload,
                privacy_intent=pi,
            )
            audit_step("tamper.participants", True, note="removed receiver from participants")
        if attacks.get("tamper_msg1_payload") and env.privacy_intent is not None:
            # Modify the payload without updating intent.payload_hash; should trigger INTENT_PAYLOAD_MISMATCH.
            if isinstance(env.payload, str):
                mutated = env.payload + "A"
            else:
                mutated = {"_tampered": True, "original": env.payload}
            env = ProtocolEnvelope(
                operation=env.operation,
                phase=env.phase,
                session_id=env.session_id,
                payload=mutated,
                privacy_intent=env.privacy_intent,
            )
            audit_step("tamper.msg1_payload", True, note="modified msg1 payload")
        nonlocal captured_intent
        if captured_intent is None and env.privacy_intent is not None:
            captured_intent = dict(env.privacy_intent)

        # Record the exact on-wire envelope (after any tampering) for the Envelope tab.
        envelopes.append(
            {
                "dir": "initiator -> receiver",
                **_envelope_to_dict(env),
                "privacy_intent": env.privacy_intent,
            }
        )

        # Mirror receiver-side checks for step-by-step clarity.
        try:
            initiator_pubkey_hex = (_ap3_ext_decoded(initiator_agent._card) or {}).get("public_key_hex")  # type: ignore[attr-defined]
            initiator_pubkey = bytes.fromhex(initiator_pubkey_hex) if initiator_pubkey_hex else b""
        except Exception:
            initiator_pubkey = b""
        if initiator_pubkey:
            for name, ok, details in _receiver_checks_from_intent(
                envelope=env, receiver_url=receiver_url, initiator_public_key=initiator_pubkey
            ):
                audit_step(name, ok, **details)

        reply = await original_send(peer_url=peer_url, envelope=env, context_id=context_id)
        if reply is not None:
            envelopes.append(
                {
                    "dir": "receiver -> initiator",
                    **_envelope_to_dict(reply),
                    "privacy_intent": reply.privacy_intent,
                }
            )
        return reply

    initiator_agent._core._peer_client.send_envelope = _send_envelope_tampered  # type: ignore[method-assign]

    # Replay: run once, then re-send the exact same first-round envelope again.
    # We do this by wrapping send_envelope and capturing the first envelope.
    first_envelope: dict[str, Any] = {}

    async def _send_envelope_capture_first(
        *,
        peer_url: str,
        envelope: ProtocolEnvelope,
        context_id: Optional[str] = None,
    ):
        if not first_envelope and envelope.privacy_intent is not None:
            first_envelope.update(
                {"peer_url": peer_url, "envelope": envelope, "context_id": context_id}
            )
        return await _send_envelope_tampered(
            peer_url=peer_url, envelope=envelope, context_id=context_id
        )

    if scenario == "replay" or attacks.get("replay"):
        initiator_agent._core._peer_client.send_envelope = _send_envelope_capture_first  # type: ignore[method-assign]

    # Run intent over the real HTTP servers (A2A).
    audit_step("run_intent.http", True, peer_url=receiver_url)
    try:
        psi_outcome = str(attacks.get("psi_outcome") or "successful")
        initiator_customer_data = (
            "Jane Smith,S001,456 Elm St" if psi_outcome == "successful" else "No Match,N000,0 Nowhere Rd"
        )
        result_directive = await initiator_agent.run_intent(
            peer_url=receiver_url,
            inputs={"customer_data": initiator_customer_data},
        )
    except Exception as e:
        audit_step("run_intent.error", False, error=str(e))
        _log(logs, level="error", event="ap3.playground.error", scenario=scenario, error=str(e))
        directives: dict[str, Any] = {}
        if captured_intent is not None:
            directives["intent"] = captured_intent
            directives["intent_canonical"] = _canonical_and_sig(captured_intent)
        return {
            "scenario": scenario,
            "request": {},
            "a2a_http": http_capture,
            "agent_cards": {
                "initiator": {
                    "card": _card_to_dict(initiator_agent._card),  # type: ignore[attr-defined]
                    "ap3_extension": _ap3_ext_decoded(initiator_agent._card),  # type: ignore[attr-defined]
                },
                "receiver": {
                    "card": _card_to_dict(receiver_agent._card),  # type: ignore[attr-defined]
                    "ap3_extension": _ap3_ext_decoded(receiver_agent._card),  # type: ignore[attr-defined]
                },
            },
            "psi_data": {"initiator_input": initiator_customer_data, "receiver_dataset": RECEIVER_DATASET},
            "envelopes": envelopes,
            "directives": directives,
            "audit": audit,
            "logs": logs,
            "result": {"ok": False, "error": str(e)},
        }

    # If replay scenario, re-send captured first envelope directly (receiver-side replay cache).
    if (scenario == "replay" or attacks.get("replay")) and first_envelope.get("envelope") is not None:
        audit_step("replay.second_send", True, note="resending same intent+msg1")
        try:
            reply = await receiver_agent.handle_envelope(first_envelope["envelope"])  # type: ignore[index]
            if reply is not None:
                envelopes.append(
                    {
                        "dir": "receiver (replay direct) -> initiator",
                        **_envelope_to_dict(reply),
                    }
                )
        except Exception as e:
            audit_step("replay.error", False, error=str(e))

    result_payload = result_directive.model_dump(mode="json")
    directives = {
        **(
            {
                "intent": captured_intent,
                "intent_canonical": _canonical_and_sig(captured_intent),
            }
            if captured_intent is not None
            else {}
        ),
        "result": result_payload,
        "result_canonical": _canonical_and_sig(result_payload),
    }

    return {
        "scenario": scenario,
        "request": {},
        "a2a_http": http_capture,
        "agent_cards": {
            "initiator": {
                "card": _card_to_dict(initiator_agent._card),  # type: ignore[attr-defined]
                "ap3_extension": _ap3_ext_decoded(initiator_agent._card),  # type: ignore[attr-defined]
            },
            "receiver": {
                "card": _card_to_dict(receiver_agent._card),  # type: ignore[attr-defined]
                "ap3_extension": _ap3_ext_decoded(receiver_agent._card),  # type: ignore[attr-defined]
            },
        },
        "psi_data": {"initiator_input": initiator_customer_data, "receiver_dataset": RECEIVER_DATASET},
        "envelopes": envelopes,
        "directives": directives,
        "audit": audit,
        "logs": logs,
        "result": {"ok": True, "data": result_payload.get("result_data", {})},
    }


# UI moved to `static/` files.


async def homepage(_: Any) -> Response:
    return HTMLResponse(_read_static("index.html"))


async def static_file(request: Any) -> Response:
    name = request.path_params["name"]
    try:
        data = _read_static(name)
    except FileNotFoundError:
        return Response("not found", status_code=404)
    media = "text/plain"
    if name.endswith(".js"):
        media = "application/javascript"
    elif name.endswith(".css"):
        media = "text/css"
    elif name.endswith(".html"):
        media = "text/html"
    return Response(data, media_type=media)


def _preview_agent_cards(lab: dict[str, Any]) -> dict[str, Any]:
    initiator_cfg: AgentLabConfig = (lab.get("initiator") or {})  # type: ignore[assignment]
    receiver_cfg: AgentLabConfig = (lab.get("receiver") or {})  # type: ignore[assignment]

    priv_i, pub_i = generate_keypair()
    priv_r, pub_r = generate_keypair()

    i_commit = _commitment_from_lab(agent_id="initiator", cfg=initiator_cfg)
    r_commit = _commitment_from_lab(agent_id="receiver", cfg=receiver_cfg)
    i_sig = CommitmentMetadataSystem.sign_commitment(i_commit, priv_i)
    r_sig = CommitmentMetadataSystem.sign_commitment(r_commit, priv_r)
    i_commit = i_commit.model_copy(update={"signature": i_sig})
    r_commit = r_commit.model_copy(update={"signature": r_sig})

    i_role = initiator_cfg.get("role", "ap3_initiator")
    r_role = receiver_cfg.get("role", "ap3_receiver")
    i_ops = initiator_cfg.get("supported_operations", ["PSI"])
    r_ops = receiver_cfg.get("supported_operations", ["PSI"])

    i_card = build_privacy_agent_card(
        name="Preview Initiator",
        description="Preview only",
        version="1.0.0",
        card_url="http://127.0.0.1:18082",
        skill_id="preview",
        skill_name="preview",
        skill_description="preview",
        skill_examples=[],
        roles=[i_role],
        supported_operations=i_ops,
        commitments=[i_commit],
        public_key=pub_i,
        ap3_sdk_version=_AP3_VERSION,
    )
    r_card = build_privacy_agent_card(
        name="Preview Receiver",
        description="Preview only",
        version="1.0.0",
        card_url="http://127.0.0.1:18083",
        skill_id="preview",
        skill_name="preview",
        skill_description="preview",
        skill_examples=[],
        roles=[r_role],
        supported_operations=r_ops,
        commitments=[r_commit],
        public_key=pub_r,
        ap3_sdk_version=_AP3_VERSION,
    )
    return {
        "initiator": _card_to_dict(i_card),
        "receiver": _card_to_dict(r_card),
    }


async def run_api(request: Any) -> Response:
    payload = await request.json()
    scenario = payload.get("scenario", "psi")
    if scenario not in {"psi", "compat_mismatch", "tamper_session_id", "tamper_participants", "replay"}:
        return JSONResponse({"error": "unknown scenario"}, status_code=400)

    # Capture lab configs (if present) for this run.
    lab = payload.get("lab") or {}
    setattr(_run_scenario, "_initiator_cfg", lab.get("initiator", {}))  # type: ignore[attr-defined]
    setattr(_run_scenario, "_receiver_cfg", lab.get("receiver", {}))  # type: ignore[attr-defined]
    setattr(_run_scenario, "_attacks", payload.get("attacks") or {})  # type: ignore[attr-defined]

    trace = await _run_scenario(scenario)  # type: ignore[arg-type]

    # Populate request inspector from the actual browser -> playground call.
    req_headers = {k: v for k, v in request.headers.items() if k.lower() in {"content-type", "user-agent", "accept"}}
    trace["request"] = {
        "method": request.method,
        "path": str(request.url.path),
        "headers": req_headers,
        "body": payload,
        "curl": "curl -sS -X POST http://localhost:8088/api/run -H 'content-type: application/json' -d "
        + json.dumps(payload),
    }

    return JSONResponse(trace)


# ---------------------------------------------------------------------------
# Long-lived PrivacyAgent harness (kept alive across scenario runs)
# ---------------------------------------------------------------------------


def _normalize_lab(lab: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields that affect server/card behavior."""
    def norm_agent(a: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": a.get("role", ""),
            "supported_operations": list(a.get("supported_operations") or []),
            "data_structure": a.get("data_structure", ""),
            "data_format": a.get("data_format", ""),
            "data_freshness": a.get("data_freshness", ""),
            "industry": a.get("industry", ""),
        }

    return {
        "initiator": norm_agent(lab.get("initiator") or {}),
        "receiver": norm_agent(lab.get("receiver") or {}),
    }


@dataclass
class _AgentHarness:
    lock: asyncio.Lock
    stack: contextlib.AsyncExitStack
    lab_key: Optional[str]
    http_capture: list[dict[str, Any]]
    initiator: Optional[PrivacyAgent]
    receiver: Optional[PrivacyAgent]


_HARNESS = _AgentHarness(
    lock=asyncio.Lock(),
    stack=contextlib.AsyncExitStack(),
    lab_key=None,
    http_capture=[],
    initiator=None,
    receiver=None,
)

_WALK: dict[str, Any] = {}  # legacy (no longer used); kept for backward compat


def _trace_base(
    *,
    scenario: str,
    http_capture: list[dict[str, Any]],
    initiator_agent: PrivacyAgent,
    receiver_agent: PrivacyAgent,
    initiator_input: str,
) -> Trace:
    return {
        "scenario": scenario,
        "request": {},
        "a2a_http": http_capture,
        "agent_cards": {
            "initiator": {
                "card": _card_to_dict(initiator_agent._card),  # type: ignore[attr-defined]
                "ap3_extension": _ap3_ext_decoded(initiator_agent._card),  # type: ignore[attr-defined]
            },
            "receiver": {
                "card": _card_to_dict(receiver_agent._card),  # type: ignore[attr-defined]
                "ap3_extension": _ap3_ext_decoded(receiver_agent._card),  # type: ignore[attr-defined]
            },
        },
        "psi_data": {"initiator_input": initiator_input, "receiver_dataset": RECEIVER_DATASET},
        "envelopes": [],
        "directives": {},
        "audit": [],
        "logs": [],
        "result": {"ok": True, "data": {}},
    }


async def walkthrough_reset_api(_: Any) -> Response:
    walk_id = str(uuid.uuid4())
    _WALKS[walk_id] = WalkState(
        walk_id=walk_id,
        created_at=time.time(),
        last_used=time.time(),
    )
    return JSONResponse({"ok": True, "walk_id": walk_id})


async def walkthrough_send_msg1_api(request: Any) -> Response:
    try:
        payload = await request.json()
        walk_id = payload.get("walk_id")
        if not walk_id:
            return JSONResponse({"ok": False, "error": "missing walk_id"}, status_code=400)
        w = _get_walk(str(walk_id))
        lab = payload.get("lab") or {}
        attacks = payload.get("attacks") or {}
        norm = _normalize_lab(lab)
        lab_key = json.dumps(norm, sort_keys=True, separators=(",", ":"))

        initiator_agent, receiver_agent, _ = await _ensure_agents(lab)
        receiver_url = "http://127.0.0.1:18083"

        psi_outcome = str(attacks.get("psi_outcome") or "successful")
        initiator_customer_data = (
            "Jane Smith,S001,456 Elm St" if psi_outcome == "successful" else "No Match,N000,0 Nowhere Rd"
        )

        # Reset per-walk state if lab config changes.
        async with w.lock:
            if w.lab_key != lab_key:
                w.lab_key = lab_key
                w.wire_sid = None
                w.internal_sid = None
                w.intent_payload = None
                w.msg1_outgoing = None
                w.reply = None
                w.trace_base = None
                w.http_capture = []

        # Build base trace.
        trace: Trace = _trace_base(
            scenario="walkthrough",
            http_capture=w.http_capture,
            initiator_agent=initiator_agent,
            receiver_agent=receiver_agent,
            initiator_input=initiator_customer_data,
        )

        # Start operation and build signed intent + first envelope (mirrors PrivacyAgent.run_intent).
        peer = await initiator_agent._core._peer_client.resolve_peer(receiver_url)  # type: ignore[attr-defined]
        initiator_agent._core._assert_compatible(peer)  # type: ignore[attr-defined]

        start = initiator_agent._core._operation.start(role="initiator", inputs={"customer_data": initiator_customer_data})
        internal_sid = start["session_id"]
        outgoing = start.get("outgoing")
        if outgoing is None:
            return JSONResponse({"ok": False, "error": "operation.start returned no outgoing"}, status_code=400)

        wire_sid = outgoing.get("protocol_session") or internal_sid
        intent = initiator_agent._core._build_signed_intent(  # type: ignore[attr-defined]
            session_id=wire_sid,
            peer_url=receiver_url,
            payload=outgoing["message"],
            expiry_hours=DEFAULT_INTENT_EXPIRY_HOURS,
        )
        intent_payload = intent.model_dump(mode="json")

        envelope = ProtocolEnvelope(
            operation=initiator_agent._core._operation.operation_id,  # type: ignore[attr-defined]
            phase=outgoing.get("phase", "msg1"),
            session_id=wire_sid,
            payload=outgoing["message"],
            privacy_intent=intent_payload,
        )

        # Apply tampering attacks directly to the outbound envelope.
        if attacks.get("tamper_session_id"):
            envelope = ProtocolEnvelope(
                operation=envelope.operation,
                phase=envelope.phase,
                session_id="tampered-" + envelope.session_id,
                payload=envelope.payload,
                privacy_intent=envelope.privacy_intent,
            )
        if attacks.get("tamper_participants") and envelope.privacy_intent is not None:
            pi = dict(envelope.privacy_intent)
            pi["participants"] = ["http://127.0.0.1:18082", "http://someone-else.example"]
            envelope = ProtocolEnvelope(
                operation=envelope.operation,
                phase=envelope.phase,
                session_id=envelope.session_id,
                payload=envelope.payload,
                privacy_intent=pi,
            )
        if attacks.get("tamper_msg1_payload") and envelope.privacy_intent is not None:
            mutated = (
                (envelope.payload + "A")
                if isinstance(envelope.payload, str)
                else {"_tampered": True, "original": envelope.payload}
            )
            envelope = ProtocolEnvelope(
                operation=envelope.operation,
                phase=envelope.phase,
                session_id=envelope.session_id,
                payload=mutated,
                privacy_intent=envelope.privacy_intent,
            )

        # Record outbound envelope + receiver-side check mirror (what will be verified).
        trace["envelopes"].append(
            {"dir": "initiator -> receiver", **_envelope_to_dict(envelope), "privacy_intent": envelope.privacy_intent}
        )
        initiator_pubkey_hex = (_ap3_ext_decoded(initiator_agent._card) or {}).get("public_key_hex")  # type: ignore[attr-defined]
        initiator_pubkey = bytes.fromhex(initiator_pubkey_hex) if initiator_pubkey_hex else b""
        if initiator_pubkey:
            for name, ok, details in _receiver_checks_from_intent(
                envelope=envelope, receiver_url=receiver_url, initiator_public_key=initiator_pubkey
            ):
                trace["audit"].append({"ts_ms": 0, "name": name, "ok": ok, "details": details})

        # Send and capture reply, but DO NOT process it yet (we finalize on Step 5).
        token = _walk_id_ctx.set(w.walk_id)
        try:
            reply = await initiator_agent._core._peer_client.send_envelope(  # type: ignore[attr-defined]
                peer_url=receiver_url,
                envelope=envelope,
                context_id=f"{initiator_agent._core._operation.operation_id}_{wire_sid[:8]}",  # type: ignore[attr-defined]
            )
        finally:
            _walk_id_ctx.reset(token)

        if reply is not None:
            # Store reply for later finalize; if it's an error, surface it immediately
            # and stop the walkthrough on the client.
            async with w.lock:
                w.reply = reply
            trace["envelopes"].append(
                {
                    "dir": "receiver -> initiator",
                    **_envelope_to_dict(reply),
                    "privacy_intent": reply.privacy_intent,
                }
            )
            if reply.error is not None:
                trace["result"] = {"ok": False, "error": reply.error}

        async with w.lock:
            w.wire_sid = wire_sid
            w.internal_sid = internal_sid
            w.intent_payload = intent_payload
            w.msg1_outgoing = outgoing
            w.trace_base = trace

        trace["directives"]["intent"] = intent_payload
        trace["directives"]["intent_canonical"] = _canonical_and_sig(intent_payload)
        if trace["result"].get("ok", True):
            trace["result"] = {"ok": True, "data": {"phase": "msg1_sent"}}
        return JSONResponse(trace)
    except Exception as e:
        tb = traceback.format_exc()
        return JSONResponse(
            {"ok": False, "error": str(e), "traceback": tb},
            status_code=500,
        )


async def walkthrough_receiver_checks_api(request: Any) -> Response:
    payload = await request.json()
    walk_id = payload.get("walk_id")
    if not walk_id:
        return JSONResponse({"ok": False, "error": "missing walk_id"}, status_code=400)
    w = _get_walk(str(walk_id))
    async with w.lock:
        trace = w.trace_base
    if trace is None:
        return JSONResponse({"ok": False, "error": "walkthrough not started"}, status_code=400)
    return JSONResponse(trace)


async def walkthrough_finalize_api(request: Any) -> Response:
    payload = await request.json()
    walk_id = payload.get("walk_id")
    if not walk_id:
        return JSONResponse({"ok": False, "error": "missing walk_id"}, status_code=400)
    w = _get_walk(str(walk_id))
    async with w.lock:
        trace = w.trace_base
        reply: Optional[ProtocolEnvelope] = w.reply
        wire_sid = w.wire_sid
        internal_sid = w.internal_sid
    if trace is None or reply is None or wire_sid is None or internal_sid is None:
        return JSONResponse({"ok": False, "error": "missing walkthrough state; run step 3 first"}, status_code=400)

    # Append receiver->initiator envelope now.
    trace["envelopes"].append({"dir": "receiver -> initiator", **_envelope_to_dict(reply), "privacy_intent": reply.privacy_intent})

    if reply.error is not None:
        trace["result"] = {"ok": False, "error": reply.error}
        return JSONResponse(trace)

    # Finalize on initiator (mirrors PrivacyAgent.run_intent post-reply path).
    initiator_agent = _HARNESS.initiator
    if initiator_agent is None:
        return JSONResponse({"ok": False, "error": "initiator not running"}, status_code=500)

    processed = initiator_agent._core._operation.process(  # type: ignore[attr-defined]
        session_id=internal_sid,
        message={"phase": reply.phase, "message": reply.payload},
    )
    if not processed.get("done"):
        trace["result"] = {"ok": False, "error": "unexpected: protocol not done after msg2"}
        return JSONResponse(trace)

    result_directive = initiator_agent._core.build_signed_result(  # type: ignore[attr-defined]
        session_id=wire_sid,
        operation_result=processed.get("result") or {},
    )
    result_payload = result_directive.model_dump(mode="json")
    trace["directives"]["result"] = result_payload
    trace["directives"]["result_canonical"] = _canonical_and_sig(result_payload)
    trace["result"] = {"ok": True, "data": result_payload.get("result_data", {})}
    return JSONResponse(trace)


async def _ensure_agents(lab: dict[str, Any]) -> tuple[PrivacyAgent, PrivacyAgent, list[dict[str, Any]]]:
    """Start agents once and keep them alive; restart if lab config changes."""
    norm = _normalize_lab(lab)
    lab_key = json.dumps(norm, sort_keys=True, separators=(",", ":"))
    async with _HARNESS.lock:
        if _HARNESS.initiator is not None and _HARNESS.receiver is not None and _HARNESS.lab_key == lab_key:
            _HARNESS.http_capture = []
            return _HARNESS.initiator, _HARNESS.receiver, _HARNESS.http_capture

        # restart
        await _HARNESS.stack.aclose()
        _HARNESS.stack = contextlib.AsyncExitStack()
        _HARNESS.http_capture = []

        def _client_factory():
            import httpx

            async def on_request(request: httpx.Request):
                url = str(request.url)
                dir_label = "initiator → receiver" if ":18083" in url else ("receiver → initiator" if ":18082" in url else "")
                wid = _walk_id_ctx.get()
                target = _HARNESS.http_capture
                if wid and wid in _WALKS:
                    target = _WALKS[wid].http_capture
                target.append(
                    {
                        "ts": _now_iso(),
                        "type": "request",
                        "dir": dir_label,
                        "method": request.method,
                        "url": url,
                        "headers": {k: v for k, v in request.headers.items()},
                        "body": request.content.decode("utf-8", errors="replace") if request.content else "",
                    }
                )

            async def on_response(response: httpx.Response):
                body = await response.aread()
                text = body.decode("utf-8", errors="replace")
                if len(text) > 64_000:
                    text = text[:64_000] + "\n…(truncated)…"
                url = str(response.request.url)
                dir_label = "initiator → receiver" if ":18083" in url else ("receiver → initiator" if ":18082" in url else "")
                wid = _walk_id_ctx.get()
                target = _HARNESS.http_capture
                if wid and wid in _WALKS:
                    target = _WALKS[wid].http_capture
                target.append(
                    {
                        "ts": _now_iso(),
                        "type": "response",
                        "dir": dir_label,
                        "status_code": response.status_code,
                        "url": url,
                        "headers": {k: v for k, v in response.headers.items()},
                        "body": text,
                    }
                )

            return httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
                event_hooks={"request": [on_request], "response": [on_response]},
            )

        initiator_cfg: AgentLabConfig = norm["initiator"]  # type: ignore[assignment]
        receiver_cfg: AgentLabConfig = norm["receiver"]  # type: ignore[assignment]

        i_priv, i_pub = generate_keypair()
        r_priv, r_pub = generate_keypair()

        initiator_url = "http://127.0.0.1:18082"
        receiver_url = "http://127.0.0.1:18083"

        initiator_peer_client = PeerClient(httpx_client_factory=_client_factory)
        receiver_peer_client = PeerClient(httpx_client_factory=_client_factory)

        initiator_agent = PrivacyAgent(
            name="AP3 Playground Initiator",
            description="Runs PSI (playground)",
            card_url=initiator_url,
            host="127.0.0.1",
            port=18082,
            role=initiator_cfg.get("role") or "ap3_initiator",
            operation=PSIOperation(),
            commitment=_commitment_from_lab(agent_id="initiator", cfg=initiator_cfg),
            private_key=i_priv,
            public_key=i_pub,
            peer_client=initiator_peer_client,
        )
        receiver_agent = PrivacyAgent(
            name="AP3 Playground Receiver",
            description="Receives PSI (playground)",
            card_url=receiver_url,
            host="127.0.0.1",
            port=18083,
            role=receiver_cfg.get("role") or "ap3_receiver",
            operation=PSIOperation(),
            commitment=_commitment_from_lab(agent_id="receiver", cfg=receiver_cfg),
            private_key=r_priv,
            public_key=r_pub,
            peer_client=receiver_peer_client,
            receiver_config_provider=lambda: {
                "sanction_list": RECEIVER_DATASET
            },
            # Playground runs both sides on 127.0.0.1, which the receiver
            # would otherwise reject as SSRF-unsafe.
            allow_private_initiator_urls=True,
        )

        # Apply advertised supported ops to cards (affects compatibility).
        if initiator_cfg.get("supported_operations"):
            _apply_supported_ops_to_card(initiator_agent._card, initiator_cfg["supported_operations"])  # type: ignore[attr-defined]
        if receiver_cfg.get("supported_operations"):
            _apply_supported_ops_to_card(receiver_agent._card, receiver_cfg["supported_operations"])  # type: ignore[attr-defined]

        await _HARNESS.stack.enter_async_context(initiator_agent.serving())
        await _HARNESS.stack.enter_async_context(receiver_agent.serving())

        _HARNESS.initiator = initiator_agent
        _HARNESS.receiver = receiver_agent
        _HARNESS.lab_key = lab_key
        return initiator_agent, receiver_agent, _HARNESS.http_capture


async def compat_api(request: Any) -> Response:
    payload = await request.json()
    lab = payload.get("lab") or {}
    initiator_cfg: AgentLabConfig = lab.get("initiator", {}) or {}
    receiver_cfg: AgentLabConfig = lab.get("receiver", {}) or {}

    # Build AP3 params objects without running servers.
    from ap3.types import AP3ExtensionParameters

    try:
        p1 = AP3ExtensionParameters.model_validate(
            {
                "roles": [initiator_cfg.get("role", "ap3_initiator")],
                "supported_operations": initiator_cfg.get("supported_operations", ["PSI"]),
                "commitments": [
                    _commitment_from_lab(agent_id="initiator", cfg=initiator_cfg).model_dump(mode="json")
                ],
            }
        )
        p2 = AP3ExtensionParameters.model_validate(
            {
                "roles": [receiver_cfg.get("role", "ap3_receiver")],
                "supported_operations": receiver_cfg.get("supported_operations", ["PSI"]),
                "commitments": [
                    _commitment_from_lab(agent_id="receiver", cfg=receiver_cfg).model_dump(mode="json")
                ],
            }
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
        p1, p2, operation_type="PSI"
    )
    return JSONResponse(
        {
            "ok": True,
            "score": score,
            "min_score": CommitmentCompatibilityChecker.MIN_COMPAT_SCORE,
            "compatible": CommitmentCompatibilityChecker.is_compatible_score(score),
            "explanation": explanation,
        }
    )


async def agentcards_api(request: Any) -> Response:
    payload = await request.json()
    lab = payload.get("lab") or {}
    try:
        cards = _preview_agent_cards(lab)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return JSONResponse({"ok": True, **cards})


_UI_ASSETS_MOVED = True

APP_JS = ""


routes = [
    Route("/", homepage, methods=["GET"]),
    Route("/static/{name}", static_file, methods=["GET"]),
    Route("/api/run", run_api, methods=["POST"]),
    Route("/api/walkthrough/reset", walkthrough_reset_api, methods=["POST"]),
    Route("/api/walkthrough/send_msg1", walkthrough_send_msg1_api, methods=["POST"]),
    Route("/api/walkthrough/receiver_checks", walkthrough_receiver_checks_api, methods=["POST"]),
    Route("/api/walkthrough/finalize", walkthrough_finalize_api, methods=["POST"]),
    Route("/api/compat", compat_api, methods=["POST"]),
    Route("/api/agentcards", agentcards_api, methods=["POST"]),
]

app = Starlette(routes=routes)

