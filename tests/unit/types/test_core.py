"""Unit tests for core AP3 types (ap3/types/core.py)."""

import pytest
from datetime import datetime, timezone
import hashlib
import base64

from ap3.types.core import (
    DataStructure,
    DataFormat,
    DataFreshness,
    CoverageArea,
    Industry,
    DataSchema,
    CommitmentMetadata,
    ResultData,
    OperationType,
    AP3Role,
)


class TestEnums:
    """Test enum types."""

    @pytest.mark.unit
    def test_data_structure_enum(self):
        """Test DataStructure enum values."""
        assert DataStructure.BLACKLIST == "blacklist"
        assert DataStructure.CUSTOMER_LIST == "customer_list"
        assert DataStructure.SUPPLY_CHAIN_DATA == "supply_chain_data"
        assert DataStructure.PRODUCT_CATALOG == "product_catalog"

    @pytest.mark.unit
    def test_data_format_enum(self):
        """Test DataFormat enum values."""
        assert DataFormat.STRUCTURED == "structured"
        assert DataFormat.UNSTRUCTURED == "unstructured"
        assert DataFormat.SEMI_STRUCTURED == "semi_structured"
        assert DataFormat.BINARY == "binary"

    @pytest.mark.unit
    def test_data_freshness_enum(self):
        """Test DataFreshness enum values."""
        assert DataFreshness.REAL_TIME == "real_time"
        assert DataFreshness.DAILY == "daily"
        assert DataFreshness.WEEKLY == "weekly"

    @pytest.mark.unit
    def test_coverage_area_enum(self):
        """Test CoverageArea enum values."""
        assert CoverageArea.GLOBAL == "global"
        assert CoverageArea.REGIONAL == "regional"
        assert CoverageArea.LOCAL == "local"

    @pytest.mark.unit
    def test_industry_enum(self):
        """Test Industry enum values."""
        assert Industry.FOOD_DELIVERY == "food_delivery"
        assert Industry.RETAIL == "retail"
        assert Industry.FINANCE == "finance"
        assert Industry.MANUFACTURING == "manufacturing"


class TestLiteralTypes:
    """Test literal type aliases."""

    @pytest.mark.unit
    def test_operation_type(self):
        """Test OperationType literal type."""
        # These should be valid values
        op1: OperationType = "PSI"
        op2: OperationType = "PIR"
        assert op1 == "PSI"
        assert op2 == "PIR"

    @pytest.mark.unit
    def test_ap3_role(self):
        """Test AP3Role literal type."""
        role1: AP3Role = "ap3_initiator"
        role2: AP3Role = "ap3_receiver"

        assert role1 == "ap3_initiator"
        assert role2 == "ap3_receiver"


class TestDataSchema:
    """Test DataSchema model."""

    @pytest.mark.unit
    def test_create_basic_schema(self):
        """Test creating a basic DataSchema."""
        schema = DataSchema(
            structure=DataStructure.CUSTOMER_LIST,
            format=DataFormat.STRUCTURED,
            fields=["name", "email"],
        )

        assert schema.structure == DataStructure.CUSTOMER_LIST
        assert schema.format == DataFormat.STRUCTURED
        assert schema.fields == ["name", "email"]
        assert schema.constraints == {}
        assert schema.metadata == {}

    @pytest.mark.unit
    def test_create_schema_with_constraints(self):
        """Test creating DataSchema with constraints."""
        constraints = {"email": "valid_email", "name": "max_length:100"}
        schema = DataSchema(
            structure=DataStructure.USER_PROFILES,
            format=DataFormat.STRUCTURED,
            fields=["name", "email", "age"],
            constraints=constraints,
        )

        assert schema.constraints == constraints
        assert "email" in schema.constraints

    @pytest.mark.unit
    def test_create_schema_with_metadata(self):
        """Test creating DataSchema with metadata."""
        metadata = {"version": "1.0", "source": "api"}
        schema = DataSchema(
            structure=DataStructure.TRANSACTION_LOG,
            format=DataFormat.STRUCTURED,
            fields=["transaction_id", "amount"],
            metadata=metadata,
        )

        assert schema.metadata == metadata


class TestCommitmentMetadata:
    """Test CommitmentMetadata model."""

    @pytest.mark.unit
    def test_create_commitment_metadata(self, sample_commitment_metadata):
        """Test creating CommitmentMetadata."""
        assert sample_commitment_metadata.commitment_id == "commit_test123"
        assert sample_commitment_metadata.agent_id == "agent_001"
        assert sample_commitment_metadata.entry_count == 1000
        assert sample_commitment_metadata.field_count == 3

    @pytest.mark.unit
    def test_validate_metadata_success(self, sample_commitment_metadata):
        """Test successful metadata validation."""
        assert sample_commitment_metadata.validate_metadata()

    @pytest.mark.unit
    def test_validate_metadata_negative_entry_count(self):
        """Test validation fails with negative entry count."""
        metadata = CommitmentMetadata(
            commitment_id="test",
            agent_id="agent",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.STRUCTURED,
            entry_count=-1,  # Invalid
            field_count=3,
            estimated_size_mb=1.0,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.DAILY,
            industry=Industry.RETAIL,
        )

        with pytest.raises(ValueError, match="entry_count must be non-negative"):
            metadata.validate_metadata()

    @pytest.mark.unit
    def test_validate_metadata_negative_field_count(self):
        """Test validation fails with negative field count."""
        metadata = CommitmentMetadata(
            commitment_id="test",
            agent_id="agent",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.STRUCTURED,
            entry_count=100,
            field_count=-1,  # Invalid
            estimated_size_mb=1.0,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.DAILY,
            industry=Industry.RETAIL,
        )

        with pytest.raises(ValueError, match="field_count must be non-negative"):
            metadata.validate_metadata()


class TestAP3ExtensionParameters:
    """Test AP3ExtensionParameters model."""

    @pytest.mark.unit
    def test_create_extension_params(self, sample_ap3_extension_params):
        """Test creating AP3ExtensionParameters."""
        assert "ap3_initiator" in sample_ap3_extension_params.roles
        assert "PSI" in sample_ap3_extension_params.supported_operations
        assert len(sample_ap3_extension_params.commitments) == 1

    @pytest.mark.unit
    def test_get_agent_card_extension(self, sample_ap3_extension_params):
        """Test getting agent card extension format."""
        extension = sample_ap3_extension_params.get_agent_card_extension()

        assert "uri" in extension
        assert "description" in extension
        assert "params" in extension
        assert extension["uri"] == "https://github.com/lfdt-ap3/ap3"
        assert "params" in extension
        assert "roles" in extension["params"]



class TestResultData:
    """Test ResultData model."""

    @pytest.mark.unit
    def test_create_result_data(self, sample_result_data):
        """Test creating ResultData."""
        assert sample_result_data.encoded_result is not None
        assert sample_result_data.result_hash is not None
        assert "computation_time" in sample_result_data.metadata

    @pytest.mark.unit
    def test_decrypt_result(self):
        """Test decrypting result data."""
        original_value = "42"
        encoded = base64.b64encode(original_value.encode()).decode()
        result_hash = hashlib.sha256(original_value.encode()).hexdigest()

        result_data = ResultData(
            encoded_result=encoded,
            result_hash=result_hash,
            metadata={}
        )

        decoded = result_data.decode()
        assert decoded == original_value
        # Backwards-compat: decrypt() still works.
        assert result_data.decrypt() == original_value

    @pytest.mark.unit
    def test_decrypt_invalid_data(self):
        """Test decrypting invalid data raises error."""
        result_data = ResultData(
            encoded_result="not_valid_base64!@#",
            result_hash="abc123",
            metadata={}
        )

        with pytest.raises(ValueError, match="Failed to decode"):
            result_data.decode()
        with pytest.raises(ValueError, match="Failed to decode"):
            result_data.decrypt()

    @pytest.mark.unit
    def test_verify_integrity_success(self):
        """Test successful integrity verification."""
        original_value = "test_result"
        encoded = base64.b64encode(original_value.encode()).decode()
        result_hash = hashlib.sha256(original_value.encode()).hexdigest()

        result_data = ResultData(
            encoded_result=encoded,
            result_hash=result_hash,
            metadata={}
        )

        assert result_data.verify_integrity()

    @pytest.mark.unit
    def test_verify_integrity_with_expected_value(self):
        """Test integrity verification with expected value."""
        original_value = "100"
        encoded = base64.b64encode(original_value.encode()).decode()
        result_hash = hashlib.sha256(original_value.encode()).hexdigest()

        result_data = ResultData(
            encoded_result=encoded,
            result_hash=result_hash,
            metadata={}
        )

        assert result_data.verify_integrity("100")
        assert not result_data.verify_integrity("200")

    @pytest.mark.unit
    def test_verify_integrity_failure(self):
        """Test integrity verification failure with tampered data."""
        original_value = "test"
        encoded = base64.b64encode(original_value.encode()).decode()
        wrong_hash = hashlib.sha256("different".encode()).hexdigest()

        result_data = ResultData(
            encoded_result=encoded,
            result_hash=wrong_hash,
            metadata={}
        )

        assert not result_data.verify_integrity()


class TestOperationProofs:
    """Test OperationProofs model."""

    @pytest.mark.unit
    def test_create_operation_proofs(self, sample_operation_proofs):
        """Test creating OperationProofs."""
        assert sample_operation_proofs.correctness_proof is not None
        assert sample_operation_proofs.privacy_proof is not None
        assert sample_operation_proofs.verification_proof is not None

    @pytest.mark.unit
    def test_proof_methods_not_implemented(self, sample_operation_proofs):
        """Test that proof verification methods raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            sample_operation_proofs.verify_all()

        with pytest.raises(NotImplementedError):
            sample_operation_proofs.verify_correctness()

        with pytest.raises(NotImplementedError):
            sample_operation_proofs.verify_privacy()
