##Added methods to make sdk user-friendly.
"""Privacy-preserving computation directives for AP3."""

from datetime import datetime
from datetime import timezone
from typing import Literal, Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .core import OperationProofs, OperationType, ResultData
from ap3.signing.canonical import canonical_json_bytes

# Data keys for A2A message parts
PRIVACY_INTENT_DIRECTIVE_DATA_KEY = "ap3.directives.PrivacyIntentDirective"
PRIVACY_RESULT_DIRECTIVE_DATA_KEY = "ap3.directives.PrivacyResultDirective"

# Domain-separation prefixes for signed directive bytes.
#
# Without this, two structurally similar directives (e.g. PrivacyIntent and a
# future PrivacyConsent) could share a byte-identical canonical body, letting
# an attacker re-route a captured signature across types. The prefix is binary
# and contains a NUL, so it cannot appear inside a canonical JSON object.
_INTENT_DOMAIN = b"AP3v1\x00ap3.directives.PrivacyIntentDirective\x00"
_RESULT_DOMAIN = b"AP3v1\x00ap3.directives.PrivacyResultDirective\x00"
# User as protocol category and then specific Type

class PrivacyIntentDirective(BaseModel):
    """Defines the privacy-preserving computation to be performed.

    This directive is created by the initiator agent to specify what
    privacy-preserving computation should be performed and what
    requirements must be satisfied.

    `extra="forbid"`: signed directives must not silently drop unknown
    fields. If two implementations disagree on the field set, the receiver
    must reject — otherwise the verifier would canonicalize a strict
    subset and produce a signature mismatch on legitimate traffic.
    """

    model_config = ConfigDict(extra="forbid")

    ap3_session_id: str = Field(..., description="Unique identifier for this session")
    intent_directive_id: str = Field(..., description="Unique identifier for this privacy intent")
    operation_type: OperationType = Field(
        ..., description="Type of privacy-preserving operation (e.g. PSI)"
    )
    participants: list[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description=(
            "Exactly two participants: [initiator_url, receiver_url]. "
            "Locked to a pair so a single signed intent cannot be submitted "
            "to multiple receivers (each would find itself in the list). "
            "Multi-party operations should redesign per-receiver binding."
        ),
    )
    nonce: str = Field(
        "",
        description=(
            "Initiator-chosen unique nonce for anti-replay. "
            "Must be unique at least per (initiator, ap3_session_id)."
        ),
    )
    payload_hash: str = Field(
        "",
        description=(
            "SHA-256 hex of the on-wire payload this intent rides on. "
            "Binds the signed intent to the envelope's payload — preventing a "
            "malicious middle from swapping payloads. Each envelope from the "
            "initiator carries its own intent with its own payload_hash."
        ),
    )
    expiry: str = Field(..., description="Expiry time in ISO 8601 format")
    signature: Optional[str] = Field(
        None,
        description="Cryptographic signature of the initiator agent"
    )
    ## sdk now provides OOP interface instead of importing helper functions in the examples
    
    
    def validate_directive(self) -> tuple[bool, Optional[str]]:
        """Check if this intent directive is valid.
        
        Returns:
            (is_valid, error_message) - None if valid
        """
        # Exactly two participants: [initiator, receiver].
        if len(self.participants) != 2:
            return False, "participants must contain exactly 2 entries [initiator, receiver]"
        
        # Check expiry
        if self.is_expired():
            return False, "Directive has expired"
        
        # Valid operation type (pydantic already enforces the Literal)
        if self.operation_type not in ["PSI"]:
            return False, f"Invalid operation type: {self.operation_type}"

        if not isinstance(self.nonce, str) or not self.nonce.strip():
            return False, "Missing nonce"

        if not isinstance(self.payload_hash, str) or len(self.payload_hash) != 64:
            return False, "Invalid payload_hash"
        
        return True, None
    
    def is_expired(self) -> bool:
        """Check if this directive has expired."""
        # Parse ISO timestamp and compare with current time
        try:
            expiry_dt = datetime.fromisoformat(self.expiry.replace('Z', '+00:00'))
            now_dt = datetime.now(timezone.utc)
            return now_dt > expiry_dt
        except (ValueError, AttributeError):
            # If timestamp is invalid, treat as expired to be safe
            return True
    
    def sign(self, private_key: bytes) -> str:
        """Sign this directive with the given Ed25519 private key.

        Signs all fields except ``signature`` itself. Stores the result
        as a base64 string and returns it.

        Args:
            private_key: 32-byte Ed25519 private key.

        Returns:
            Base64-encoded Ed25519 signature string.
        """
        import base64
        from ap3.signing.primitives import sign as crypto_sign
        body = canonical_json_bytes(self.model_dump(mode="python", exclude={"signature"}, exclude_none=True))
        sig_bytes = crypto_sign(_INTENT_DOMAIN + body, private_key)
        return base64.b64encode(sig_bytes).decode()

    def verify_signature(self, public_key: bytes) -> bool:
        """Verify the Ed25519 signature on this directive.

        Args:
            public_key: 32-byte Ed25519 public key of the signer.

        Returns:
            True if the signature is present and valid, False otherwise.
        """
        import base64
        from ap3.signing.primitives import verify as crypto_verify
        if not self.signature:
            return False
        body = canonical_json_bytes(self.model_dump(mode="python", exclude={"signature"}, exclude_none=True))
        try:
            sig_bytes = base64.b64decode(self.signature)
        except Exception:
            return False
        return crypto_verify(_INTENT_DOMAIN + body, sig_bytes, public_key)
class PrivacyResultDirective(BaseModel):
    """Contains the computation result with cryptographic proofs.

    This directive contains the result of the privacy-preserving computation
    along with cryptographic proofs that verify the correctness and
    privacy preservation of the operation.

    `extra="forbid"`: see `PrivacyIntentDirective`.
    """

    model_config = ConfigDict(extra="forbid")

    ap3_session_id: str = Field(..., description="Unique identifier for this session")
    result_directive_id: str = Field(..., description="Unique identifier for this result directive")
    result_data: ResultData = Field(..., description="Encoded result data and metadata")
    proofs: OperationProofs = Field(..., description="Cryptographic proofs of correctness and privacy")
    # Required, top-level, part of the signed body. The intent is that a
    # casual integrator who calls `directive.verify_signature(pubkey)` and
    # gets True still has to look at this field to learn whether the result
    # itself is attested. Today the SDK only ever emits
    # "experimental_placeholders"; "verified" is reserved for when real
    # proof generation/verification lands.
    attestation: Literal["unattested", "experimental_placeholders", "verified"] = Field(
        ...,
        description=(
            "Attestation level for the proofs in this directive. "
            "'experimental_placeholders' means `proofs` are deterministic "
            "stand-ins, NOT cryptographic guarantees. 'verified' is reserved "
            "for future real proof generation."
        ),
    )
    signature: Optional[str] = Field(
        None,
        description="Cryptographic signature of the initiator agent"
    )

    def validate_directive(self) -> tuple[bool, Optional[str]]:
        """Check if result directive and proofs are valid."""
        if not self.result_data.result_hash:
            return False, "Missing result hash"

        if not self.proofs.correctness_proof:
            return False, "Missing correctness proof"

        if not self.proofs.privacy_proof:
            return False, "Missing privacy proof"

        return True, None
    
    def sign(self, private_key: bytes) -> str:
        """Sign this result directive with the given Ed25519 private key.

        Args:
            private_key: 32-byte Ed25519 private key.

        Returns:
            Base64-encoded Ed25519 signature string.
        """
        import base64
        from ap3.signing.primitives import sign as crypto_sign
        body = canonical_json_bytes(self.model_dump(mode="python", exclude={"signature"}, exclude_none=True))
        sig_bytes = crypto_sign(_RESULT_DOMAIN + body, private_key)
        return base64.b64encode(sig_bytes).decode()

    def verify_signature(self, public_key: bytes) -> bool:
        """Verify the Ed25519 signature on this result directive.

        Args:
            public_key: 32-byte Ed25519 public key of the signer.

        Returns:
            True if the signature is present and valid, False otherwise.
        """
        import base64
        from ap3.signing.primitives import verify as crypto_verify
        if not self.signature:
            return False
        body = canonical_json_bytes(self.model_dump(mode="python", exclude={"signature"}, exclude_none=True))
        try:
            sig_bytes = base64.b64decode(self.signature)
        except Exception:
            return False
        return crypto_verify(_RESULT_DOMAIN + body, sig_bytes, public_key)
    
    def verify_proofs(self) -> bool:
        """Verify all cryptographic proofs.

        Raises:
            NotImplementedError: real proof generation/verification is not
                wired up yet; only attestation="verified" results would be
                eligible to pass this check, and the SDK never emits that.
            ValueError: the directive carries placeholder/unattested proofs
                and must not be treated as cryptographically attested.
        """
        if self.attestation != "verified":
            raise ValueError(
                f"refusing to verify proofs: attestation={self.attestation!r}; "
                "this directive does not carry real cryptographic proofs"
            )
        raise NotImplementedError("Proof verification not yet implemented")


class PrivacyError(BaseModel):
    """Error information for privacy-preserving operation failures."""

    error_code: str = Field(..., description="Machine-readable error code")
    error_message: str = Field(..., description="Human-readable error message")

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.error_message}"
    operation_type: Optional[str] = Field(
        None,
        description="Operation directive that failed"
    )
    recovery_options: list[str] = Field(
        default_factory=list,
        description="Available recovery options"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp when the privacy-preserving operation error occurred"
    )


class PrivacyProtocolError(Exception):
    """Raised when an AP3 privacy protocol run is refused/invalid.

    This wraps a structured `PrivacyError` model for programmatic access.
    """

    def __init__(self, error: PrivacyError):
        self.error = error
        super().__init__(str(error))


class PrivacyViolationError(BaseModel):
    """Error information for privacy-preserving operation violations."""

    error_code: str = Field(..., description="Machine-readable error code")
    error_message: str = Field(..., description="Human-readable error message")

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.error_message}"
    violation_type: str = Field(..., description="Type of privacy-preserving operation violation detected")
    allowed_reveal: str = Field(..., description="What was allowed to be revealed during the operation")
    actual_reveal: str = Field(..., description="What was actually revealed during the operation")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp when the privacy-preserving operation violation was detected"
    )
