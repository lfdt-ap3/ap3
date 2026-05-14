"""Pytest configuration and shared fixtures for AP3 tests."""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import uuid

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ap3.types import (
    DataStructure,
    DataFormat,
    DataFreshness,
    CoverageArea,
    Industry,
    DataSchema,
    CommitmentMetadata,
    AP3ExtensionParameters,
    PrivacyIntentDirective,
    PrivacyResultDirective,
    ResultData,
    OperationProofs,
)


# ============================================================================
# Time-related fixtures
# ============================================================================

@pytest.fixture
def current_time():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


@pytest.fixture
def future_time(current_time):
    """Get a time 24 hours in the future."""
    return current_time + timedelta(hours=24)


@pytest.fixture
def past_time(current_time):
    """Get a time 24 hours in the past."""
    return current_time - timedelta(hours=24)


# ============================================================================
# Core type fixtures
# ============================================================================

@pytest.fixture
def sample_data_schema():
    """Create a sample DataSchema for testing."""
    return DataSchema(
        structure=DataStructure.CUSTOMER_LIST,
        format=DataFormat.STRUCTURED,
        fields=["name", "email", "phone"],
        constraints={"email": "valid_email", "phone": "E.164_format"},
        metadata={"industry": "retail", "coverage_area": "global"}
    )


@pytest.fixture
def sample_commitment_metadata():
    """Create sample CommitmentMetadata for testing."""
    return CommitmentMetadata(
        commitment_id="commit_test123",
        agent_id="agent_001",
        data_structure=DataStructure.CUSTOMER_LIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=1000,
        field_count=3,
        estimated_size_mb=2.5,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.DAILY,
        coverage_area=CoverageArea.GLOBAL,
        industry=Industry.RETAIL,
    )


@pytest.fixture
def sample_ap3_extension_params(sample_commitment_metadata):
    """Create sample AP3ExtensionParameters for testing."""
    return AP3ExtensionParameters(
        roles=["ap3_initiator"],
        supported_operations=["PSI"],
        commitments=[sample_commitment_metadata]
    )


# ============================================================================
# Directive fixtures
# ============================================================================

@pytest.fixture
def sample_session_id():
    """Generate a sample session ID."""
    return str(uuid.uuid4())


@pytest.fixture
def sample_privacy_intent_directive(sample_session_id, future_time):
    """Create sample PrivacyIntentDirective for testing."""
    return PrivacyIntentDirective(
        ap3_session_id=sample_session_id,
        intent_directive_id=str(uuid.uuid4()),
        operation_type="PSI",
        participants=["http://agent1.example.com", "http://agent2.example.com"],
        nonce="nonce_test",
        payload_hash="0" * 64,
        expiry=future_time.isoformat(),
        signature=None
    )


@pytest.fixture
def sample_result_data():
    """Create sample ResultData for testing."""
    import base64
    import hashlib

    result_value = "42"
    encoded = base64.b64encode(result_value.encode()).decode()
    result_hash = hashlib.sha256(result_value.encode()).hexdigest()

    return ResultData(
        encoded_result=encoded,
        result_hash=result_hash,
        metadata={"computation_time": "2.5s", "elements_processed": "100"}
    )


@pytest.fixture
def sample_operation_proofs(sample_session_id):
    """Create sample OperationProofs for testing."""
    import hashlib

    return OperationProofs(
        correctness_proof=hashlib.sha256(f"correctness_{sample_session_id}".encode()).hexdigest(),
        privacy_proof=hashlib.sha256(f"privacy_{sample_session_id}".encode()).hexdigest(),
        verification_proof=hashlib.sha256(f"verification_{sample_session_id}".encode()).hexdigest(),
    )


@pytest.fixture
def sample_privacy_result_directive(sample_session_id, sample_result_data, sample_operation_proofs):
    """Create sample PrivacyResultDirective for testing."""
    return PrivacyResultDirective(
        ap3_session_id=sample_session_id,
        result_directive_id=str(uuid.uuid4()),
        result_data=sample_result_data,
        proofs=sample_operation_proofs,
        attestation="experimental_placeholders",
        signature=None,
    )


# ============================================================================
# Mock fixtures for services
# ============================================================================

@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx AsyncClient for testing."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_agent_card():
    """Create a mock agent card for testing."""
    return {
        "name": "Test Agent",
        "description": "A test agent for unit testing",
        "version": "1.0.0",
        "capabilities": {
            "extensions": [
                {
                    "uri": "https://github.com/lfdt-ap3/ap3/tree/main",
                    "description": "AP3 extension",
                    "params": {
                        "roles": ["ap3_receiver"],
                        "supported_operations": ["PSI"],
                        "commitments": [
                            {
                                "commitment_id": "commit_123",
                                "agent_id": "agent_test",
                                "data_structure": "customer_list",
                                "data_format": "structured",
                                "entry_count": 1000,
                                "field_count": 3,
                                "estimated_size_mb": 2.5,
                                "last_updated": datetime.now(timezone.utc).isoformat(),
                                "data_freshness": "daily",
                                "coverage_area": "global",
                                "industry": "retail"
                            }
                        ]
                    }
                }
            ]
        }
    }


# ============================================================================
# Protocol test data fixtures
# ============================================================================

@pytest.fixture
def protocol_test_values():
    """Test values for protocol operations."""
    return {
        "ob_values": [5, 10],
        "cb_values": [3, 7],
        "expected_dot_product": 85  # (5*3) + (10*7) = 15 + 70 = 85
    }


@pytest.fixture
def psi_test_data():
    """Test data for PSI operations."""
    return {
        "customer_data": "John Doe,ID123,123 Main St",
        "sanction_list": [
            "Jane Smith,ID456,456 Oak Ave",
            "Bob Johnson,ID789,789 Pine Rd",
            "Alice Williams,ID321,321 Elm St"
        ],
        "sanctioned_customer": "Jane Smith,ID456,456 Oak Ave"
    }


# ============================================================================
# Utility fixtures
# ============================================================================

@pytest.fixture
def temp_csv_file(tmp_path):
    """Create a temporary CSV file for testing."""
    csv_file = tmp_path / "test_params.csv"
    csv_file.write_text(
        "parameter,value,description\n"
        "TEST_PARAM_1,100,First test parameter\n"
        "TEST_PARAM_2,200,Second test parameter\n"
    )
    return csv_file


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset any global state between tests."""
    yield
    # Add cleanup code here if needed
