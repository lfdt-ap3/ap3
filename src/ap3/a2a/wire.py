"""AP3 protocol envelope — the on-wire format between two AP3 agents.

This module is the interop contract: two different companies shipping two
different codebases must produce and consume bit-identical JSON here.
Everything else in `ap3.a2a` can be reworked without breaking peers as long
as this module's schema stays stable.

Protocol messages travel inside A2A `Part.data` (not `Part.text`) so they
are never confusable with natural language and never reach an LLM.
"""

from __future__ import annotations

from typing import Any, Optional

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct, Value
from pydantic import BaseModel, ConfigDict, Field

from a2a.types import Part

AP3_WIRE_VERSION = "1.0"
AP3_ENVELOPE_DATA_KEY = "ap3.wire.ProtocolEnvelope"

# Soft cap on the JSON-encoded size of a single envelope. Operators should
# *also* set their HTTP server's request-body limit (e.g. starlette's
# max_request_size); this cap is a defense-in-depth check so a peer cannot
# send a 2 GiB envelope that fits under the HTTP cap but starves the
# receiver of memory before AP3 logic runs. Tighten per deployment.
MAX_ENVELOPE_JSON_BYTES = 4 * 1024 * 1024


class ProtocolEnvelope(BaseModel):
    """One protocol round-trip message, framework-neutral.

    `payload` carries whatever bytes/strings the underlying `Operation`
    emitted (e.g. ECDH ciphertext for PSI). The envelope does not interpret
    it. `privacy_intent` is present on msg1; `privacy_result` is present on
    the final message of operations where the initiator attests to the
    result. Both are `dict` rather than the typed directive models because
    the envelope must round-trip through JSON on both sides without
    requiring the peer to have the exact same pydantic version.

    `extra="forbid"`: an unrecognized field on the wire is a peer
    advertising a capability we do not implement. Silently dropping it
    risks signature/verification mismatches across implementations, so we
    reject the envelope outright.
    """

    model_config = ConfigDict(extra="forbid")

    ap3_wire_version: str = Field(default=AP3_WIRE_VERSION)
    operation: str = Field(..., description="Operation ID, e.g. 'psi'")
    phase: str = Field(..., description="Operation-defined phase, e.g. 'msg1', 'msg2'")
    session_id: str = Field(..., description="AP3 session identifier (base64 or hex)")
    payload: Any = Field(..., description="Opaque protocol payload from the Operation")
    error: Optional[dict] = Field(
        default=None,
        description=(
            "PrivacyError serialized dict — present when the peer refuses the protocol "
            "or cannot process the message. When present, `payload` should be ignored."
        ),
    )
    privacy_intent: Optional[dict] = Field(
        default=None,
        description="PrivacyIntentDirective serialized dict — present on msg1 only",
    )
    privacy_result: Optional[dict] = Field(
        default=None,
        description="PrivacyResultDirective serialized dict — present on result-attesting messages",
    )


def envelope_to_part(envelope: ProtocolEnvelope) -> Part:
    """Pack a protocol envelope into an A2A data-part.

    Lives in the `data` oneof of `Part`, never in `text`. This is how we
    guarantee protocol bytes never reach an LLM — text parts go to the
    model, data parts go to the protocol handler.
    """
    struct = Struct()
    struct.update({AP3_ENVELOPE_DATA_KEY: envelope.model_dump(mode="json")})
    return Part(data=Value(struct_value=struct))


def envelope_from_parts(parts: list[Part]) -> Optional[ProtocolEnvelope]:
    """Extract the AP3 envelope from a list of A2A parts, if any.

    Returns None (not raises) when there is no envelope — callers use that
    as the signal to route the message to an LLM or other text handler.

    Refuses if more than one part advertises an AP3 envelope: a peer that
    attaches two envelopes to a single message is either buggy or
    attempting to sneak a second message past whichever envelope we'd
    process first. Refuses oversized envelopes for the same reason — the
    HTTP layer should already reject them, but a soft cap here means a
    misconfigured edge proxy doesn't translate into an OOM.
    """
    found: list[dict] = []
    for part in parts:
        if part.WhichOneof("content") != "data":
            continue
        data = MessageToDict(part.data)
        struct_value = data.get("structValue") or data
        raw = struct_value.get(AP3_ENVELOPE_DATA_KEY) if isinstance(struct_value, dict) else None
        if raw is None:
            continue
        found.append(raw)
    if not found:
        return None
    if len(found) > 1:
        raise ValueError(
            f"AP3 envelope appears on {len(found)} parts; expected at most one"
        )
    raw = found[0]
    # Cheap length proxy without re-serializing — `Struct` -> dict gives us
    # the on-wire shape, and JSON is the canonical encoding for transit.
    try:
        import json as _json
        encoded_size = len(_json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    except Exception:
        encoded_size = 0
    if encoded_size > MAX_ENVELOPE_JSON_BYTES:
        raise ValueError(
            f"AP3 envelope too large: {encoded_size} bytes "
            f"(max {MAX_ENVELOPE_JSON_BYTES})"
        )
    return ProtocolEnvelope.model_validate(raw)
