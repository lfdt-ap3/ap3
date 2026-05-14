from dataclasses import dataclass

from merlin_transcripts import MerlinTranscript

from ap3_functions.psi.psi_internal.constants import DLOG_LABEL, POINT_SIZE, SCALAR_SIZE
from ap3_functions.psi.psi_internal.ristretto import RistrettoPoint, Scalar

DLOG_PROOF_SIZE = POINT_SIZE + SCALAR_SIZE


@dataclass
class DLogProof:
    """
    Non-interactive Schnorr ZK DLOG Proof scheme with a Fiat-Shamir transformation
    """
    t: RistrettoPoint
    s: Scalar

    def to_bytes(self) -> bytes:
        return self.t.to_bytes() + self.s.to_bytes()

    @staticmethod
    def from_bytes(data: bytes) -> "DLogProof":
        if len(data) != DLOG_PROOF_SIZE:
            raise ValueError(f"Expected {DLOG_PROOF_SIZE} bytes, got {len(data)}")

        return DLogProof(
            t=RistrettoPoint.from_bytes(data[:32]),
            s=Scalar.from_bytes(data[32:]),
        )

    @staticmethod
    def fiat_shamir(
        y: RistrettoPoint,
        w: RistrettoPoint,
        base_point: RistrettoPoint,
        session_id: bytes
    ) -> Scalar:
        """ Get fiat-shamir challenge for Discrete log proof"""
        t = MerlinTranscript(DLOG_LABEL)
        t.append_message(b'session_id', session_id)
        t.append_message(b'role', b'BB-dlog-proof')
        t.append_message(b'y', y.to_bytes())
        t.append_message(b't', w.to_bytes())
        t.append_message(b'base-point', base_point.to_bytes())
        output = t.challenge_bytes(b'challenge-bytes', 64)
        return Scalar.from_bytes_wide(bytes(output))

    @staticmethod
    def prove(x: Scalar, base_point: RistrettoPoint, session_id: bytes) -> "DLogProof":
        """y = x * base_point"""
        y = base_point * x
        r = Scalar.random()
        t = base_point * r
        c = DLogProof.fiat_shamir(y, t, base_point, session_id)
        s = r + c * x
        return DLogProof(t, s)

    def verify(
        self,
        y: RistrettoPoint,
        base_point: RistrettoPoint,
        session_id: bytes,
    ) -> bool:
        c = self.fiat_shamir(y, self.t, base_point, session_id)
        lhs = base_point * self.s
        rhs = self.t + y * c
        return lhs == rhs
