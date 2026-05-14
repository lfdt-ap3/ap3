"""Pre-fetch SSRF guard for unverified peer URLs.

The receiver pulls an initiator URL out of an unauthenticated envelope and,
to verify the signature, has to fetch the initiator's AgentCard from that
URL. Without this guard an attacker can force the receiver to issue an HTTP
GET against any address the receiver can reach — `169.254.169.254` cloud
metadata, RFC1918 internals, the receiver's own admin port — before any
signature check has run. This module classifies a URL as "obviously
unsafe" by scheme + host *literal*, with no DNS lookup, so the check is
cheap and side-effect-free. DNS rebinding is out of scope here; if the
caller needs that level of guarantee, do post-resolution validation in
the HTTP client.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

# Hostnames that almost always resolve to local/private targets. We block by
# name in addition to IP literals so an attacker can't bypass with `localhost`.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
        # Common cloud / container metadata aliases.
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
    }
)


class UnsafeInitiatorURL(ValueError):
    """Raised when an unverified URL points at a private/loopback/metadata target."""


def assert_safe_initiator_url(url: str, *, allow_private: bool = False) -> None:
    """Reject URLs that would let an attacker SSRF the receiver.

    `allow_private=True` is the dev/test escape hatch — the playground and
    quickstart examples both run on `127.0.0.1`, so they pass it explicitly.
    Production receivers should leave it at the default.
    """
    if not isinstance(url, str) or not url:
        raise UnsafeInitiatorURL("initiator_url is empty")

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeInitiatorURL(
            f"initiator_url scheme must be http or https, got {scheme!r}"
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeInitiatorURL("initiator_url has no host")

    if allow_private:
        return

    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeInitiatorURL(
            f"initiator_url host {host!r} resolves to a local target"
        )

    # Bracketed IPv6 hosts come through urlsplit already unwrapped.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal — accept. DNS-based attacks are out of scope.
        return

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise UnsafeInitiatorURL(
            f"initiator_url host {host} is not a routable public address"
        )
