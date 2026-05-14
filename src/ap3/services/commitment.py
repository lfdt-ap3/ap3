"""Commitment creation and management for AP3 Protocol."""

import base64
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ap3.types import (
    CommitmentMetadata,
    CoverageArea,
    DataFreshness,
    DataSchema,
    DataStructure,
)

from ap3.signing.primitives import generate_keypair
from ap3.signing.canonical import canonical_json_bytes

# Domain-separation prefix for signed commitments. Binary string with embedded
# NUL bytes so it cannot collide with canonical JSON output (see
# `ap3.types.directive` for the same pattern on directive signatures).
_COMMITMENT_DOMAIN = b"AP3v1\x00ap3.commitments.CommitmentMetadata\x00"


class CommitmentMetadataSystem:
    """System for creating and managing commitment metadata."""

    def __init__(self, *, signing_private_key: bytes | None = None, signing_public_key: bytes | None = None):
        self.commitments: Dict[str, CommitmentMetadata] = {}
        self._blinding_factors: Dict[str, int] = {}
        if signing_private_key is None or signing_public_key is None:
            self._private_key, self.public_key = generate_keypair()
        else:
            self._private_key = signing_private_key
            self.public_key = signing_public_key

    def create_commitment(
        self,
        agent_id: str,
        data_schema: DataSchema,
        entry_count: int,
        data_hash: str,
        expiry: Optional[str] = None,
    ) -> CommitmentMetadata:
        """Create a structured commitment.

        Args:
            agent_id: Agent creating the commitment
            data_schema: Schema definition for the data
            entry_count: Number of entries in the data
            data_hash: Hash of the actual data
            expiry: Optional expiry timestamp

        Returns:
            CommitmentMetadata with generated ID, cryptographic fields, and signature
        """
        new_id = self._create_unique_id()
        now = self._get_current_time_iso()

        size_mb = self._calculate_approximate_size(entry_count, len(data_schema.fields))

        freshness_map = {
            "real_time": DataFreshness.REAL_TIME,
            "daily": DataFreshness.DAILY,
            "weekly": DataFreshness.WEEKLY,
        }
        freshness_str = data_schema.metadata.get("update_frequency", "daily")
        freshness_enum = freshness_map.get(freshness_str, DataFreshness.DAILY)

        coverage_map = {
            "global": CoverageArea.GLOBAL,
            "regional": CoverageArea.REGIONAL,
            "local": CoverageArea.LOCAL,
        }
        coverage_str = data_schema.metadata.get("coverage_area", "global")
        coverage_enum = coverage_map.get(coverage_str.lower(), CoverageArea.GLOBAL)

        industry_val = data_schema.metadata.get("industry", "other")

        commitment = CommitmentMetadata(
            commitment_id=new_id,
            agent_id=agent_id,
            data_structure=data_schema.structure,
            data_format=data_schema.format,
            entry_count=entry_count,
            field_count=len(data_schema.fields),
            estimated_size_mb=size_mb,
            last_updated=now,
            data_freshness=freshness_enum,
            coverage_area=coverage_enum,
            industry=industry_val,
            data_schema=data_schema,
            data_hash=data_hash,
            expiry=expiry,
        )

        signature = self._sign_commitment(commitment)
        commitment = commitment.model_copy(update={"signature": signature})
        self.commitments[new_id] = commitment

        return commitment

    def get_public_metadata(self, commitment_id: str) -> Optional[CommitmentMetadata]:
        """Get metadata for a commitment."""
        return self.commitments.get(commitment_id)

    def search_commitments(
        self,
        data_structure: Optional[DataStructure] = None,
        min_entry_count: Optional[int] = None,
        max_entry_count: Optional[int] = None,
        coverage_area: Optional[CoverageArea] = None,
    ) -> List[CommitmentMetadata]:
        """Search for commitments matching criteria."""
        matches = []

        for commitment in self.commitments.values():
            if data_structure and commitment.data_structure != data_structure:
                continue
            # `is not None` rather than truthy: a caller asking for
            # max_entry_count=0 means "only empty datasets" — a truthy
            # check would silently turn that into "no filter".
            if min_entry_count is not None and commitment.entry_count < min_entry_count:
                continue
            if max_entry_count is not None and commitment.entry_count > max_entry_count:
                continue
            if coverage_area and commitment.coverage_area != coverage_area:
                continue
            matches.append(commitment)

        return matches

    def verify_commitment_integrity(
        self, commitment_id: str, actual_data: List[Any]
    ) -> bool:
        """Verify that actual data matches the commitment."""
        stored = self.commitments.get(commitment_id)
        if not stored:
            return False

        if len(actual_data) != stored.entry_count:
            return False

        if stored.data_hash is not None:
            current_hash = self._hash_data_content(actual_data)
            if current_hash != stored.data_hash:
                return False

        if stored.data_schema is not None:
            if not self._validate_against_schema(actual_data, stored.data_schema):
                return False

        return True

    def _calculate_approximate_size(self, num_entries: int, num_fields: int) -> float:
        """Calculate approximate data size in MB (heuristic: ~100 bytes/field/entry)."""
        bytes_est = num_entries * num_fields * 100
        return bytes_est / (1024 * 1024)

    def _validate_against_schema(self, dataset: List[Any], schema: DataSchema) -> bool:
        if not dataset:
            return True
        return all(self._validate_item_against_schema(item, schema) for item in dataset)

    def _validate_item_against_schema(self, item: Any, schema: DataSchema) -> bool:
        if isinstance(item, dict):
            for required_field in schema.fields:
                if required_field not in item:
                    return False
        elif isinstance(item, str):
            if schema.constraints:
                return self._check_string_format(item, schema.constraints)
        else:
            return False
        return True

    def _check_string_format(self, text_data: str, constraints: Dict[str, Any]) -> bool:
        for key, _ in constraints.items():
            if key == "person_id_format":
                if not text_data.startswith("DS_"):
                    return False
            elif key == "phone_format":
                if not text_data.startswith("+"):
                    return False
        return True

    def _hash_data_content(self, data: List[Any]) -> str:
        return hashlib.sha256(canonical_json_bytes(data)).hexdigest()

    def _create_unique_id(self) -> str:
        return f"commit_{secrets.token_hex(16)}"

    def _get_current_time_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def sign_commitment(commitment: CommitmentMetadata, private_key: bytes) -> str:
        """Sign a commitment with the given Ed25519 private key.

        The signature is over all fields except `signature` itself, encoded via
        canonical JSON (stable across languages).
        """
        from ap3.signing.primitives import sign

        payload = commitment.model_dump(mode="python", exclude={"signature"}, exclude_none=True)
        sig_bytes = sign(_COMMITMENT_DOMAIN + canonical_json_bytes(payload), private_key)
        return base64.b64encode(sig_bytes).decode()

    @staticmethod
    def verify_commitment_signature(commitment: CommitmentMetadata, public_key: bytes) -> bool:
        """Verify a commitment signature against an Ed25519 public key."""
        from ap3.signing.primitives import verify

        if not commitment.signature:
            return False
        try:
            sig = base64.b64decode(commitment.signature)
        except Exception:
            return False
        payload = commitment.model_dump(mode="python", exclude={"signature"}, exclude_none=True)
        return verify(_COMMITMENT_DOMAIN + canonical_json_bytes(payload), sig, public_key)

    def _sign_commitment(self, commitment: CommitmentMetadata) -> str:
        # Backwards-compatible internal signing (uses system keypair).
        return CommitmentMetadataSystem.sign_commitment(commitment, self._private_key)
