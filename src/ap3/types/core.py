"""Core types for AP3."""

from typing import Literal, Optional, Any
from enum import Enum
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import AliasChoices

#### Operation types
OperationType = Literal["PSI"]

#### Role types
AP3Role = Literal["ap3_initiator", "ap3_receiver"]

#### Commitment types
class DataStructure(str, Enum):
    """Supported data structures for commitments."""
    BLACKLIST = "blacklist"
    CUSTOMER_LIST = "customer_list"
    TRANSACTION_LOG = "transaction_log"
    PRODUCT_CATALOG = "product_catalog"
    SUPPLY_CHAIN_DATA = "supply_chain_data"
    FINANCIAL_RECORDS = "financial_records"
    USER_PROFILES = "user_profiles"
    INVENTORY_DATA = "inventory_data"

class DataFormat(str, Enum):
    """Supported data formats for commitments."""
    STRUCTURED = "structured"  # JSON, CSV, etc.
    UNSTRUCTURED = "unstructured"  # Free text
    SEMI_STRUCTURED = "semi_structured"  # Mixed format
    BINARY = "binary"  # Binary data

class DataFreshness(str, Enum):
    """Supported data freshness for commitments."""
    REAL_TIME = "real_time"
    DAILY = "daily"
    WEEKLY = "weekly"

class CoverageArea(str, Enum):
    """Geographic coverage area for commitments"""
    GLOBAL = "global"
    REGIONAL = "regional"
    LOCAL = "local"

class Industry(str, Enum):
    """Supported industries for commitments."""
    FOOD_DELIVERY = "food_delivery"
    RETAIL = "retail"
    FINANCE = "finance"
    MANUFACTURING = "manufacturing"
    HEALTHCARE = "healthcare"
    TRANSPORTATION = "transportation"
    OTHER = "other"

class DataSchema(BaseModel):
    """Schema definition for committed data."""
    structure: DataStructure
    format: DataFormat
    fields: list[str] = Field(..., description="Field names in the data")
    constraints: dict[str, Any] = Field(
        default_factory=dict, 
        description="Data constraints (e.g., field formats, value ranges)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional schema metadata"
    )

class CommitmentMetadata(BaseModel):
    """Commitment containing both public metadata and cryptographic fields.

    `extra="forbid"`: this object is signed via `CommitmentMetadataSystem.
    sign_commitment`. An unknown field on the wire would canonicalize
    differently across implementations, breaking verification.
    """

    model_config = ConfigDict(extra="forbid")

    commitment_id: str
    agent_id: str = Field(..., description="Agent that owns this commitment")
    data_structure: DataStructure
    data_format: DataFormat
    entry_count: int
    field_count: int
    estimated_size_mb: float
    last_updated: str
    data_freshness: DataFreshness
    coverage_area: CoverageArea = Field(
        default=CoverageArea.GLOBAL,
        description="Geographic coverage area"
    )
    industry: Industry
    # Cryptographic and schema fields (populated when created via CommitmentMetadataSystem)
    data_schema: Optional["DataSchema"] = Field(
        default=None,
        description="Full schema definition for the committed data"
    )
    data_hash: Optional[str] = Field(
        default=None,
        description="Hash of actual data for integrity verification"
    )
    expiry: Optional[str] = Field(
        default=None,
        description="Expiry time in ISO 8601 format"
    )
    signature: Optional[str] = Field(
        default=None,
        description="Cryptographic signature over the commitment"
    )

    def validate_metadata(self) -> bool:
        """Check if commitment metadata is valid (counts aren't negative, etc)."""
        # Basic sanity checks - could be extended later
        if self.entry_count < 0:
            raise ValueError("entry_count must be non-negative")
        if self.field_count < 0:
            raise ValueError("field_count must be non-negative")
        if self.estimated_size_mb < 0:
            raise ValueError("estimated_size_mb must be non-negative")
        return True

#### Extension parameters
class AP3ExtensionParameters(BaseModel):
    """Extension parameters for AP3 agent cards."""

    roles: list[AP3Role] = Field(
        ...,
        min_length=1,
        description="The roles this agent performs in the AP3 model"
    )
    supported_operations: list[str] = Field(
        ...,
        min_length=1,
        description="Types of privacy-preserving operations supported"
    )
    commitments: list[CommitmentMetadata] = Field(
        ...,
        description="Data commitments this agent supports for privacy-preserving computations"
    )
    
    def get_agent_card_extension(self) -> dict:
        """Get the extension object for adding to agent cards.
        
        This formats the AP3 params in the structure needed for agent card extensions.
        """
        return {
            "uri": "https://github.com/lfdt-ap3/ap3",
            "description": "AP3 extension for privacy-preserving agent collaboration",
            "params": self.model_dump(mode='python'),
            "required": True
        }

class ResultData(BaseModel):
    """Result data from privacy computation.

    NOTE: In the current SDK, the result is only base64-encoded, not encrypted.
    The field is named `encoded_result` to avoid implying confidentiality.

    `extra="forbid"`: nested inside the signed `PrivacyResultDirective`, so
    unknown fields must not be silently dropped (would break verification).
    """

    model_config = ConfigDict(extra="forbid")

    encoded_result: str = Field(
        ...,
        validation_alias=AliasChoices("encoded_result", "encrypted_result"),
        description="Base64-encoded computation result (not encrypted in current SDK)",
    )
    result_hash: str = Field(..., description="Hash of the result for integrity verification")
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Metadata about the computation (e.g., computation time, elements processed)"
    )
    
    
    def decode(self) -> str:
        """Decode the result (base64 decode).
        
        Returns:
            str: Decoded result as string
        """
        import base64
        try:
            decoded_bytes = base64.b64decode(self.encoded_result)
            return decoded_bytes.decode("utf-8")
        except Exception as e:
            raise ValueError(f"Failed to decode result: {e}")

    def decrypt(self, key: bytes | None = None) -> str:
        """Deprecated: use decode().

        Retained for backwards compatibility with earlier SDK versions.
        The `key` argument is accepted but ignored — the result is base64-encoded,
        not encrypted, in the current SDK.
        """
        del key
        return self.decode()
    
    def verify_integrity(self, expected_value: str = "") -> bool:
        """Verify result hash matches the decrypted data.
        
        Args:
            expected_value: Optional expected value to verify against.
                          If not provided, verifies hash of decrypted data.
        
        Returns:
            bool: True if integrity check passes
        """
        import hashlib
        
        try:
            # If expected value provided, check against that
            if len(expected_value) > 1:
                expected_hash = hashlib.sha256(str(expected_value).encode()).hexdigest()
                return self.result_hash == expected_hash
            
            # Otherwise, verify hash matches decrypted data
            decoded = self.decode()
            computed_hash = hashlib.sha256(decoded.encode()).hexdigest()
            return self.result_hash == computed_hash
        except Exception:
            return False


class OperationProofs(BaseModel):
    """Experimental proof container (placeholder).

    WARNING: These fields are **not** cryptographic proofs yet.
    The current SDK populates them with deterministic hash placeholders to
    exercise the wire format and end-to-end flow. Do not treat them as
    security guarantees until real proof generation + verification lands.

    `extra="forbid"`: nested inside the signed `PrivacyResultDirective`.
    """

    model_config = ConfigDict(extra="forbid")

    correctness_proof: str = Field(
        ...,
        description="EXPERIMENTAL placeholder; not a real correctness proof yet",
    )
    privacy_proof: str = Field(
        ...,
        description="EXPERIMENTAL placeholder; not a real privacy proof yet",
    )
    verification_proof: str = Field(
        ...,
        description="EXPERIMENTAL placeholder; not a real verification proof yet",
    )
    
    def verify_all(self) -> bool:
        """Verify all proofs.
        
        Returns:
            bool: True if all proofs are valid
        """
        # Need to be implemented
        raise NotImplementedError("Proof verification not yet implemented")
    
    def verify_correctness(self) -> bool:
        """Verify correctness proof.
        
        Returns:
            bool: True if correctness proof is valid
        """
        # Need to be implemented
        raise NotImplementedError("Correctness proof verification not yet implemented")
    
    def verify_privacy(self) -> bool:
        """Verify privacy proof.
        
        Returns:
            bool: True if privacy proof is valid
        """
        # Need to be implemented
        raise NotImplementedError("Privacy proof verification not yet implemented")
