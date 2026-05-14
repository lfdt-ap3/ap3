"""
FFI bindings for Private Set Intersection (PSI) protocol.
"""

import hashlib
from typing import Tuple

from ap3_functions.exceptions import ProtocolError
from ap3_functions.psi.psi_internal import (
    PSCBBInvalidSessionID,
    PSCMsg1,
    PSCMsg2,
    PSCOBInvalidDlogProofError,
    PSCOBInvalidMSG2,
    PSCStateOB,
    SESSION_ID_SIZE,
    BLIND_VALUE_SIZE,
    HASH_SIZE,
    compute_session_id,
    create_commitment,
    verify_commitment,
    psc_create_msg1,
    psc_process_msg1,
    psc_process_msg2,
)

_MAX_SANCTION_ENTRIES = 1_000_000
_MAX_MSG2_BYTES = 128 + 4 + 32 * _MAX_SANCTION_ENTRIES

__all__ = [
    "generate_hash",
    "create_psc_msg1",
    "process_psc_msg1",
    "process_psc_msg2",
    "compute_session_id",
    "create_commitment",
    "verify_commitment",
    "SESSION_ID_SIZE",
    "BLIND_VALUE_SIZE",
    "HASH_SIZE",
]


# ===============================================================================
# Public API Functions
# ===============================================================================
def generate_hash(data: str, type_flag: str = "Customer") -> bytes:
    """Generate a cryptographic hash of data.

    Args:
        data: Data to hash
        type_flag: Type flag for the hash (default: "Customer")

    Returns:
        32-byte hash
    """
    h = hashlib.sha256()
    h.update(type_flag.encode("utf-8"))
    h.update(data.encode("utf-8"))

    return h.digest()


def create_psc_msg1(
    session_id: bytes,
    customer_hash: bytes
) -> Tuple[bytes, bytes]:
    """Create PSI message 1 (initiator side).
    
    Args:
        session_id: 32-byte session ID
        customer_hash: 32-byte customer hash
        
    Returns:
        Tuple of (state, msg1) as bytes
        
    Raises:
        ProtocolError: If message creation fails
    """
    if len(customer_hash) != 32:
        raise ProtocolError("Customer hash must be 32 bytes")

    try:
        state, msg1 = psc_create_msg1(session_id, customer_hash)
        return state.to_bytes(), msg1.to_bytes()
    except ValueError as _:
        raise ProtocolError("Session ID must be 32 bytes")


def process_psc_msg1(
    session_id: bytes,
    msg1_bytes: bytes,
    sanction_list: list[bytes]
) -> bytes:
    """Process PSI message 1 and create message 2 (receiver side).
    
    Args:
        session_id: 32-byte session ID
        msg1_bytes: Message 1 from initiator
        sanction_list: List of sanctioned entities
        
    Returns:
        Message 2 to send back to initiator
        
    Raises:
        ProtocolError: If processing fails
    """
    if len(session_id) != 32:
        raise ProtocolError("Session ID must be 32 bytes", round_num=1)

    if not sanction_list:
        raise ProtocolError("sanction_list must be non-empty", round_num=1)

    if len(sanction_list) > _MAX_SANCTION_ENTRIES:
        raise ProtocolError(
            f"sanction_list too large: {len(sanction_list)} entries "
            f"(max {_MAX_SANCTION_ENTRIES})",
            round_num=1,
        )

    try:
        msg1 = PSCMsg1.from_bytes(msg1_bytes)
    except ValueError as _:
        raise ProtocolError(
            "Invalid Msg1",
            round_num=1,
        )

    try:
        msg2 = psc_process_msg1(session_id, sanction_list, msg1)
        return msg2.to_bytes()
    except PSCBBInvalidSessionID as _:
        raise ProtocolError("Invalid Session ID", round_num=1)
    except ValueError as _:
        raise ProtocolError("Invalid params for process_psc_msg1()", round_num=1)


def process_psc_msg2(
    state_bytes: bytes,
    msg2_bytes: bytes
) -> bool:
    """Process PSI message 2 and get final result (initiator side).
    
    Args:
        state_bytes: Protocol state from message 1 creation
        msg2_bytes: Message 2 from receiver
        
    Returns:
        True if match found (customer is in sanction list), False otherwise
        
    Raises:
        ProtocolError: If processing fails
    """
    if len(msg2_bytes) > _MAX_MSG2_BYTES:
        raise ProtocolError(
            f"msg2 too large: {len(msg2_bytes)} bytes (max {_MAX_MSG2_BYTES})",
            round_num=2,
        )

    try:
        state = PSCStateOB.from_bytes(state_bytes)
    except ValueError as _:
        raise ProtocolError(
            "Invalid OB State",
            round_num=2,
        )

    try:
        msg2 = PSCMsg2.from_bytes(msg2_bytes)
    except ValueError as _:
        raise ProtocolError(
            "Invalid Msg2",
            round_num=2,
        )

    try:
        return psc_process_msg2(state, msg2)
    except PSCOBInvalidMSG2 as _:
        raise ProtocolError(
            "Invalid Msg2",
            round_num=2,
        )
    except PSCOBInvalidDlogProofError as _:
        raise ProtocolError(
            "Invalid Dlog proof",
            round_num=2,
        )
