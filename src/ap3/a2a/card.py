"""Agent card builder for AP3 agents, plus peer-card introspection.

The AgentCard is how one company's agent tells another company's agent what
it can do, on what terms, and — critically — which public key to use to
verify signed directives coming from it. A peer that can't be discovered
via the card cannot be trusted, by definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
)

from ap3.a2a.wire import AP3_WIRE_VERSION
from ap3.types import AP3ExtensionParameters, CommitmentMetadata

AP3_EXTENSION_URI = "https://github.com/lfdt-ap3/ap3"
_PARAM_AP3_VERSION = "ap3_version"
_PARAM_WIRE_VERSION = "ap3_wire_version"
_PARAM_PUBLIC_KEY = "public_key_hex"

# Ed25519 public key: 32 bytes = 64 hex chars.
_ED25519_PUBKEY_HEX_LEN = 64


def normalize_url(url: str) -> str:
    """Canonicalize an agent URL so equal endpoints compare equal.

    Trailing slashes, case differences in scheme/host, and the HTTP/HTTPS
    default ports all routinely sneak into AgentCard URLs and intent
    `participants` entries. Without normalization, an initiator that signs
    an intent with `http://x.com/api/` and a receiver whose self-URL is
    `http://x.com/api` would fail the participants check on a legitimate
    request. This helper is the one place we canonicalize before comparing
    or signing.
    """
    if not url:
        return url
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host + (f":{port}" if port is not None else "")
    if parts.username or parts.password:
        userinfo = parts.username or ""
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = (parts.path or "").rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


@dataclass(frozen=True)
class PeerInfo:
    """Everything one AP3 agent needs to know about another, from its card."""

    agent_url: str
    ap3_params: AP3ExtensionParameters
    wire_version: str
    public_key: bytes
    """32-byte Ed25519 public key used to verify this peer's directives."""


def build_privacy_agent_card(
    *,
    name: str,
    description: str,
    version: str,
    card_url: str,
    skill_id: str,
    skill_name: str,
    skill_description: str,
    skill_examples: Iterable[str],
    roles: list[str],
    supported_operations: list[str],
    commitments: list[CommitmentMetadata],
    public_key: bytes,
    ap3_sdk_version: str,
) -> AgentCard:
    """Build an AgentCard with an AP3 extension block.

    The extension params include `public_key_hex` — every peer will verify
    directives signed by this agent against this exact key. Rotating the
    key means republishing the card.
    """
    if len(public_key) != 32:
        raise ValueError(
            f"Ed25519 public key must be 32 bytes, got {len(public_key)}"
        )

    skill = AgentSkill(id=skill_id, name=skill_name, description=skill_description)
    skill.examples.extend(list(skill_examples))

    card = AgentCard(
        name=name,
        description=description,
        version=version,
        capabilities=AgentCapabilities(streaming=True),
    )
    card.supported_interfaces.append(
        AgentInterface(url=f"{card_url}/", protocol_binding="JSONRPC")
    )
    card.default_input_modes.append("text")
    card.default_output_modes.append("text")
    card.skills.append(skill)

    params = Struct()
    params.update(
        {
            _PARAM_AP3_VERSION: ap3_sdk_version,
            _PARAM_WIRE_VERSION: AP3_WIRE_VERSION,
            _PARAM_PUBLIC_KEY: public_key.hex(),
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
    if card.capabilities.extensions is None:
        card.capabilities.extensions = []
    card.capabilities.extensions.append(ext)
    return card


def extract_peer_info(card: AgentCard, *, agent_url: str) -> PeerInfo:
    """Read the AP3 extension off a peer's card into a typed PeerInfo.

    Raises `ValueError` if the card has no AP3 extension, or the extension
    is missing required fields (public key, wire version). Callers should
    treat that as "this peer is not an AP3 agent — refuse to proceed."
    """
    for ext in card.capabilities.extensions or []:
        if ext.uri != AP3_EXTENSION_URI:
            continue
        params = MessageToDict(ext.params)
        pub_hex = params.get(_PARAM_PUBLIC_KEY)
        wire_version = params.get(_PARAM_WIRE_VERSION)
        if not pub_hex or not wire_version:
            raise ValueError("AP3 extension present but missing required fields")
        # Reject odd/wrong-length hex up-front so we get a clear error here
        # rather than a confusing "InvalidSignature" later when verify_signature
        # tries to use a malformed key.
        if not isinstance(pub_hex, str) or len(pub_hex) != _ED25519_PUBKEY_HEX_LEN:
            raise ValueError(
                f"AP3 extension public_key_hex must be {_ED25519_PUBKEY_HEX_LEN} hex chars; "
                f"got {len(pub_hex) if isinstance(pub_hex, str) else type(pub_hex).__name__}"
            )
        try:
            public_key = bytes.fromhex(pub_hex)
        except ValueError as e:
            raise ValueError(f"AP3 extension public_key_hex is not valid hex: {e}") from e
        return PeerInfo(
            agent_url=agent_url,
            ap3_params=AP3ExtensionParameters.model_validate(
                {
                    "roles": params.get("roles", []),
                    "supported_operations": params.get("supported_operations", []),
                    "commitments": params.get("commitments", []),
                }
            ),
            wire_version=wire_version,
            public_key=public_key,
        )
    raise ValueError(f"Peer card at {agent_url} has no AP3 extension")
