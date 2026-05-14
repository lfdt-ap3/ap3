import hashlib
import hmac
import secrets

from merlin_transcripts import MerlinTranscript

from ap3_functions.psi.psi_internal.constants import (
    H1_RO_LABEL,
    H2_RO_LABEL,
    LAMBDA_BYTES,
    SESSION_ID_LABEL,
    COMMITMENT_LABEL,
    SESSION_ID_SIZE,
    HASH_SIZE,
    BLIND_VALUE_SIZE
)
from ap3_functions.psi.psi_internal.ristretto import RistrettoPoint


def h1_function(session_id: bytes, x: bytes) -> RistrettoPoint:
    t = MerlinTranscript(H1_RO_LABEL)
    t.append_message(b'session-id', session_id)
    t.append_message(b'x', x)
    output = t.challenge_bytes(b'h1-ro-bytes', 64)
    return RistrettoPoint.from_hash(bytes(output))


def h2_function(
    session_id: bytes,
    point1: RistrettoPoint,
    point2: RistrettoPoint
) -> bytes:
    t = MerlinTranscript(H2_RO_LABEL)
    t.append_message(b'session-id', session_id)
    t.append_message(b'point1', point1.to_bytes())
    t.append_message(b'point2', point2.to_bytes())
    return bytes(t.challenge_bytes(b'h2-ro-bytes', LAMBDA_BYTES * 2))


def secure_shuffle(lst):
    lst = lst.copy()
    for i in range(len(lst) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lst[i], lst[j] = lst[j], lst[i]
    return lst


def compute_session_id(sid_0: bytes, sid_1: bytes) -> bytes:
    """Derive a PSC session_id from both parties' contributions.

    `sid_1` is BB's contribution (sent first), `sid_0` is OB's contribution
    (sent after seeing sid_1). Domain-separated with SESSION_ID_LABEL.
    """
    if len(sid_0) != SESSION_ID_SIZE or len(sid_1) != SESSION_ID_SIZE:
        raise ValueError(f"sid must be {SESSION_ID_SIZE} bytes")
    h = hashlib.sha256()
    h.update(SESSION_ID_LABEL)
    h.update(sid_0)
    h.update(sid_1)
    return h.digest()


def create_commitment(sid: bytes, blind_value: bytes) -> bytes:
    if len(sid) != SESSION_ID_SIZE:
        raise ValueError(f"sid must be {SESSION_ID_SIZE} bytes")

    if len(blind_value) != BLIND_VALUE_SIZE:
        raise ValueError(f"blind_value must be {BLIND_VALUE_SIZE} bytes")

    h = hashlib.sha256()
    h.update(COMMITMENT_LABEL)
    h.update(sid)
    h.update(blind_value)
    return h.digest()

def verify_commitment(commit: bytes, sid: bytes, blind_value: bytes) -> bool:
    if len(commit) != HASH_SIZE:
        raise ValueError(f"commit must be {HASH_SIZE} bytes")

    return hmac.compare_digest(commit, create_commitment(sid, blind_value))
