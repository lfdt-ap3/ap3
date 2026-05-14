import hmac
from dataclasses import dataclass
from typing import List, Tuple

from ap3_functions.psi.psi_internal.constants import SESSION_ID_SIZE, POINT_SIZE, SCALAR_SIZE, HASH_SIZE
from ap3_functions.psi.psi_internal.dlog_proof import DLogProof, DLOG_PROOF_SIZE
from ap3_functions.psi.psi_internal.ristretto import RistrettoPoint, Scalar
from ap3_functions.psi.psi_internal.utils import h1_function, h2_function, secure_shuffle

MSG_1_SIZE = SESSION_ID_SIZE + POINT_SIZE
STATE_OB_SIZE = SESSION_ID_SIZE + POINT_SIZE + SCALAR_SIZE + POINT_SIZE


class PSCBBInvalidSessionID(Exception):
    pass


class PSCOBInvalidMSG2(Exception):
    pass


class PSCOBInvalidDlogProofError(Exception):
    pass


@dataclass
class PSCMsg1:
    session_id: bytes
    big_a: RistrettoPoint

    def to_bytes(self) -> bytes:
        return self.session_id + self.big_a.to_bytes()

    @staticmethod
    def from_bytes(data: bytes) -> "PSCMsg1":
        if len(data) != MSG_1_SIZE:
            raise ValueError(f"Expected {MSG_1_SIZE} bytes, got {len(data)}")

        return PSCMsg1(
            session_id=data[:SESSION_ID_SIZE],
            big_a=RistrettoPoint.from_bytes(data[SESSION_ID_SIZE:]),
        )


@dataclass
class PSCMsg2:
    session_id: bytes
    big_b: RistrettoPoint
    dlog_proof: DLogProof
    hat_big_y: List[bytes]

    def to_bytes(self) -> bytes:
        hat_big_y_count = len(self.hat_big_y).to_bytes(4, "big")
        hat_big_y_bytes = b"".join(self.hat_big_y)
        return (
            self.session_id
            + self.big_b.to_bytes()
            + self.dlog_proof.to_bytes()
            + hat_big_y_count
            + hat_big_y_bytes
        )

    @staticmethod
    def from_bytes(data: bytes) -> "PSCMsg2":
        offset = 0

        if len(data) < SESSION_ID_SIZE + DLOG_PROOF_SIZE + 4:
            raise ValueError("Data too short")

        session_id = data[offset: offset + SESSION_ID_SIZE]
        offset += SESSION_ID_SIZE

        big_b = RistrettoPoint.from_bytes(data[offset: offset + POINT_SIZE])
        offset += POINT_SIZE

        dlog_proof = DLogProof.from_bytes(data[offset: offset + DLOG_PROOF_SIZE])
        offset += DLOG_PROOF_SIZE

        count = int.from_bytes(data[offset: offset + 4], "big")
        offset += 4

        expected_len = offset + count * HASH_SIZE
        if len(data) != expected_len:
            raise ValueError(f"Expected {expected_len} bytes, got {len(data)}")

        hat_big_y = [
            data[offset + i * HASH_SIZE: offset + (i + 1) * HASH_SIZE]
            for i in range(count)
        ]
        offset += count * HASH_SIZE

        return PSCMsg2(
            session_id=session_id,
            big_b=big_b,
            dlog_proof=dlog_proof,
            hat_big_y=hat_big_y,
        )


@dataclass
class PSCStateOB:
    session_id: bytes
    h1_x: RistrettoPoint
    r: Scalar
    big_a: RistrettoPoint

    def to_bytes(self) -> bytes:
        return (
            self.session_id
            + self.h1_x.to_bytes()
            + self.r.to_bytes()
            + self.big_a.to_bytes()
        )

    @staticmethod
    def from_bytes(data: bytes) -> "PSCStateOB":
        if len(data) != STATE_OB_SIZE:
            raise ValueError(f"Expected {STATE_OB_SIZE} bytes, got {len(data)}")
        offset = 0

        session_id = data[offset: offset + SESSION_ID_SIZE]
        offset += SESSION_ID_SIZE

        h1_x = RistrettoPoint.from_bytes(data[offset: offset + POINT_SIZE])
        offset += POINT_SIZE

        r = Scalar.from_bytes(data[offset: offset + SCALAR_SIZE])
        offset += SCALAR_SIZE

        big_a = RistrettoPoint.from_bytes(data[offset: offset + POINT_SIZE])

        return PSCStateOB(session_id=session_id, h1_x=h1_x, r=r, big_a=big_a)


def psc_create_msg1(session_id: bytes, x: bytes) -> Tuple[PSCStateOB, PSCMsg1]:
    """
    OB creates PSCMsg1 for BB
    """
    if len(session_id) != SESSION_ID_SIZE:
        raise ValueError("Session ID should be 32 bytes")

    r = Scalar.random()
    h1_x = h1_function(session_id, x)
    big_a = h1_x * r
    state = PSCStateOB(session_id, h1_x, r, big_a)
    msg1 = PSCMsg1(session_id, big_a)
    return state, msg1


def psc_process_msg1(session_id: bytes, big_y: List[bytes], msg1: PSCMsg1) -> PSCMsg2:
    """
    BB processes PSCMsg1 from OB
    """
    if len(session_id) != SESSION_ID_SIZE:
        raise ValueError("Session ID should be 32 bytes")

    if not hmac.compare_digest(session_id, msg1.session_id):
        raise PSCBBInvalidSessionID("Invalid Session ID")

    if not big_y:
        raise ValueError("big_y is empty")

    big_a = msg1.big_a
    k = Scalar.random()
    big_b = big_a * k

    dlog_proof = DLogProof.prove(k, big_a, session_id)

    hat_big_y = []
    for v in secure_shuffle(big_y):
        h1 = h1_function(session_id, v)
        h2 = h2_function(session_id, h1, h1 * k)
        hat_big_y.append(h2)

    return PSCMsg2(session_id, big_b, dlog_proof, hat_big_y)


def psc_process_msg2(state: PSCStateOB, msg2: PSCMsg2) -> bool:
    """
    OB processes PSCMsg2 from BB
    """
    if not hmac.compare_digest(state.session_id, msg2.session_id):
        raise PSCOBInvalidMSG2("Invalid msg2")

    big_b = msg2.big_b

    proof_valid = msg2.dlog_proof.verify(big_b, state.big_a, state.session_id)
    if not proof_valid:
        raise PSCOBInvalidDlogProofError("Invalid Dlog proof")

    r_inv = state.r.invert()
    x_hat = h2_function(state.session_id, state.h1_x, big_b * r_inv)

    return any(hmac.compare_digest(x_hat, item) for item in msg2.hat_big_y)
