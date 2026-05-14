"""AP3 over A2A — the cross-org transport, card, executor, and agent façade.

`ap3.a2a` is the layer between an AP3 `Operation` (the math) and an A2A
server/client (the wire). Anything in here is interop surface: two different
companies shipping two different codebases must see the same envelope
schema, the same card extension keys, the same signature format. Anything
specific to one company's agent framework, storage, or LLM belongs in the
company's own code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ap3.a2a.wire import (
    AP3_ENVELOPE_DATA_KEY,
    AP3_WIRE_VERSION,
    ProtocolEnvelope,
    envelope_from_parts,
    envelope_to_part,
)

if TYPE_CHECKING:
    from ap3.a2a.agent import PrivacyAgent as PrivacyAgent
    from ap3.a2a.card import (
        AP3_EXTENSION_URI as AP3_EXTENSION_URI,
        build_privacy_agent_card as build_privacy_agent_card,
        extract_peer_info as extract_peer_info,
    )
    from ap3.a2a.client import PeerClient as PeerClient, PeerInfo as PeerInfo
    from ap3.a2a.executor import (
        PrivacyAgentExecutor as PrivacyAgentExecutor,
        ProtocolHandler as ProtocolHandler,
    )


def __getattr__(name: str):
    # Lazy-import heavy / optional dependencies (A2A server stack).
    if name == "PrivacyAgent":
        from ap3.a2a.agent import PrivacyAgent as _PrivacyAgent

        return _PrivacyAgent
    if name in ("PeerClient", "PeerInfo"):
        from ap3.a2a.client import PeerClient as _PeerClient, PeerInfo as _PeerInfo

        return {"PeerClient": _PeerClient, "PeerInfo": _PeerInfo}[name]
    if name in ("AP3_EXTENSION_URI", "build_privacy_agent_card", "extract_peer_info"):
        from ap3.a2a.card import (
            AP3_EXTENSION_URI as _AP3_EXTENSION_URI,
            build_privacy_agent_card as _build_privacy_agent_card,
            extract_peer_info as _extract_peer_info,
        )

        return {
            "AP3_EXTENSION_URI": _AP3_EXTENSION_URI,
            "build_privacy_agent_card": _build_privacy_agent_card,
            "extract_peer_info": _extract_peer_info,
        }[name]
    if name in ("PrivacyAgentExecutor", "ProtocolHandler"):
        from ap3.a2a.executor import (
            PrivacyAgentExecutor as _PrivacyAgentExecutor,
            ProtocolHandler as _ProtocolHandler,
        )

        return {
            "PrivacyAgentExecutor": _PrivacyAgentExecutor,
            "ProtocolHandler": _ProtocolHandler,
        }[name]
    if name in ("AP3Middleware", "AP3Identity", "attach_ap3_extension"):
        from ap3.a2a.middleware import (
            AP3Middleware as _AP3Middleware,
            AP3Identity as _AP3Identity,
            attach_ap3_extension as _attach_ap3_extension,
        )

        return {
            "AP3Middleware": _AP3Middleware,
            "AP3Identity": _AP3Identity,
            "attach_ap3_extension": _attach_ap3_extension,
        }[name]
    raise AttributeError(name)


__all__ = [
    "AP3_WIRE_VERSION",
    "AP3_ENVELOPE_DATA_KEY",
    "ProtocolEnvelope",
    "envelope_from_parts",
    "envelope_to_part",
    "AP3_EXTENSION_URI",
    "build_privacy_agent_card",
    "extract_peer_info",
    "PeerClient",
    "PeerInfo",
    "PrivacyAgentExecutor",
    "ProtocolHandler",
    "AP3Middleware",
    "AP3Identity",
    "attach_ap3_extension",
    "PrivacyAgent",
]
