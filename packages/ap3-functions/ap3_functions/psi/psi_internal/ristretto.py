import hmac
from dataclasses import dataclass

from rbcl import crypto_core_ristretto255_scalar_random, crypto_core_ristretto255_add, crypto_scalarmult_ristretto255, \
    crypto_core_ristretto255_scalar_mul, crypto_core_ristretto255_is_valid_point, crypto_core_ristretto255_from_hash, \
    crypto_core_ristretto255_scalar_reduce, crypto_core_ristretto255_random, crypto_core_ristretto255_scalar_add, \
    crypto_core_ristretto255_scalar_invert

from ap3_functions.psi.psi_internal.constants import POINT_SIZE, SCALAR_SIZE


@dataclass
class Scalar:
    value: bytes

    def to_bytes(self) -> bytes:
        return self.value

    @staticmethod
    def from_bytes(data: bytes) -> "Scalar":
        if len(data) != SCALAR_SIZE:
            raise ValueError("Invalid scalar")

        if not any(data):
            # Zero scalar — vanishingly unlikely from honest parties, and a
            # degenerate value in DLogProof.s. Reject explicitly so a forged
            # all-zeros proof can't slip through.
            raise ValueError("Invalid scalar")

        # Canonicality check: a scalar must be in [0, L) where L is the
        # Ristretto255 group order. Non-canonical scalars (>= L) reduce to a
        # different value mod L, so feeding `data || zeros` through
        # `scalar_reduce` (which treats its 64-byte input as a 512-bit LE
        # integer and reduces mod L) and comparing returns the input
        # unchanged iff it was canonical. Without this, libsodium's
        # `scalar_mul` would silently reduce non-canonical scalars,
        # admitting wire-level malleability of `DLogProof.s`.
        canonical = crypto_core_ristretto255_scalar_reduce(data + b"\x00" * 32)
        if not hmac.compare_digest(canonical, data):
            raise ValueError("Invalid scalar")

        return Scalar(data)

    @staticmethod
    def random() -> "Scalar":
        return Scalar(crypto_core_ristretto255_scalar_random())

    @staticmethod
    def from_bytes_wide(b: bytes) -> "Scalar":
        return Scalar(crypto_core_ristretto255_scalar_reduce(b))

    def __add__(self, other: "Scalar") -> "Scalar":
        return Scalar(crypto_core_ristretto255_scalar_add(self.value, other.value))

    def __mul__(self, other: "Scalar") -> "Scalar":
        return Scalar(crypto_core_ristretto255_scalar_mul(self.value, other.value))

    def invert(self) -> "Scalar":
        return Scalar(crypto_core_ristretto255_scalar_invert(self.value))


@dataclass
class RistrettoPoint:
    value: bytes

    def to_bytes(self) -> bytes:
        return self.value

    @staticmethod
    def from_bytes(data: bytes) -> "RistrettoPoint":
        if len(data) != POINT_SIZE:
            raise ValueError("Invalid point")

        if not crypto_core_ristretto255_is_valid_point(data):
            raise ValueError("Invalid point")

        return RistrettoPoint(data)

    def __eq__(self, other):
        if isinstance(other, RistrettoPoint):
            return hmac.compare_digest(self.value, other.value)
        return NotImplemented

    @staticmethod
    def random() -> "RistrettoPoint":
        return RistrettoPoint(crypto_core_ristretto255_random())

    @staticmethod
    def from_hash(v: bytes) -> "RistrettoPoint":
        return RistrettoPoint(crypto_core_ristretto255_from_hash(v))

    def __add__(self, other: "RistrettoPoint") -> "RistrettoPoint":
        return RistrettoPoint(crypto_core_ristretto255_add(self.value, other.value))

    def __mul__(self, other: Scalar) -> "RistrettoPoint":
        return RistrettoPoint(crypto_scalarmult_ristretto255(other.value, self.value))
