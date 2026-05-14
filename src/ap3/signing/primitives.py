"""Ed25519 keypair generation, signing, and verification.

Uses the `cryptography` library. Pedersen-commitment primitives are not
shipped here; when ZK proof support lands they'll arrive in a separate
module so that `signing.primitives` stays narrow.
"""

from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


# ---------------------------------------------------------------------------
# Key generation and signing (Ed25519)
# ---------------------------------------------------------------------------

def generate_keypair() -> Tuple[bytes, bytes]:
    """Generate an Ed25519 public/private keypair.

    Returns:
        (private_key_bytes, public_key_bytes) — each 32 bytes.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes_raw()
    public_bytes = private_key.public_key().public_bytes_raw()
    return private_bytes, public_bytes


def sign(data: bytes, private_key: bytes) -> bytes:
    """Sign data with an Ed25519 private key.

    Args:
        data: The bytes to sign.
        private_key: 32-byte Ed25519 private key.

    Returns:
        64-byte Ed25519 signature.
    """
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    return key.sign(data)


def verify(data: bytes, signature: bytes, public_key: bytes) -> bool:
    """Verify an Ed25519 signature.

    Args:
        data: The original signed bytes.
        signature: 64-byte Ed25519 signature.
        public_key: 32-byte Ed25519 public key.

    Returns:
        True if the signature is valid, False otherwise.
    """
    key = Ed25519PublicKey.from_public_bytes(public_key)
    try:
        key.verify(signature, data)
        return True
    except InvalidSignature:
        return False
