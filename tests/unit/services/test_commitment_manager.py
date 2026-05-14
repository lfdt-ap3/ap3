"""Unit tests for commitment management services."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from ap3.services import (
    CommitmentMetadataSystem,
    CommitmentCompatibilityChecker,
    RemoteAgentDiscoveryService,
)
from ap3.types import (
    DataStructure,
    DataFormat,
    DataFreshness,
    CoverageArea,
    Industry,
    DataSchema,
    CommitmentMetadata,
    AP3ExtensionParameters,
)


class TestCommitmentMetadataSystem:
    """Test CommitmentMetadataSystem class."""

    @pytest.fixture
    def commitment_system(self):
        """Create a CommitmentMetadataSystem instance."""
        return CommitmentMetadataSystem()

    @pytest.mark.unit
    def test_initialization(self, commitment_system):
        """Test CommitmentMetadataSystem initialization."""
        assert len(commitment_system.commitments) == 0

    @pytest.mark.unit
    def test_create_commitment(self, commitment_system, sample_data_schema):
        """Test creating a commitment."""
        commitment = commitment_system.create_commitment(
            agent_id="agent_test",
            data_schema=sample_data_schema,
            entry_count=100,
            data_hash="test_hash_123"
        )

        assert commitment.agent_id == "agent_test"
        assert commitment.entry_count == 100
        assert commitment.data_hash == "test_hash_123"
        assert commitment.signature is not None
        assert commitment.commitment_id in commitment_system.commitments

    @pytest.mark.unit
    def test_create_commitment_with_expiry(self, commitment_system, sample_data_schema, future_time):
        """Test creating commitment with expiry."""
        commitment = commitment_system.create_commitment(
            agent_id="agent_test",
            data_schema=sample_data_schema,
            entry_count=50,
            data_hash="hash456",
            expiry=future_time.isoformat()
        )

        assert commitment.expiry == future_time.isoformat()

    @pytest.mark.unit
    def test_get_public_metadata(self, commitment_system, sample_data_schema):
        """Test retrieving public metadata for a commitment."""
        commitment = commitment_system.create_commitment(
            agent_id="agent_test",
            data_schema=sample_data_schema,
            entry_count=200,
            data_hash="hash789"
        )

        metadata = commitment_system.get_public_metadata(commitment.commitment_id)

        assert metadata is not None
        assert metadata.commitment_id == commitment.commitment_id
        assert metadata.entry_count == 200
        assert metadata.agent_id == "agent_test"

    @pytest.mark.unit
    def test_get_public_metadata_not_found(self, commitment_system):
        """Test retrieving metadata for non-existent commitment."""
        metadata = commitment_system.get_public_metadata("nonexistent_id")
        assert metadata is None

    @pytest.mark.unit
    def test_search_commitments_by_structure(self, commitment_system, sample_data_schema):
        """Test searching commitments by data structure."""
        # Create multiple commitments
        commitment_system.create_commitment(
            agent_id="agent1",
            data_schema=sample_data_schema,
            entry_count=100,
            data_hash="hash1"
        )

        other_schema = DataSchema(
            structure=DataStructure.BLACKLIST,
            format=DataFormat.STRUCTURED,
            fields=["id"],
            metadata={"industry": "retail", "coverage_area": "global"}
        )
        commitment_system.create_commitment(
            agent_id="agent2",
            data_schema=other_schema,
            entry_count=50,
            data_hash="hash2"
        )

        # Search for CUSTOMER_LIST
        results = commitment_system.search_commitments(
            data_structure=DataStructure.CUSTOMER_LIST
        )

        assert len(results) == 1
        assert results[0].data_structure == DataStructure.CUSTOMER_LIST

    @pytest.mark.unit
    def test_search_commitments_by_entry_count(self, commitment_system, sample_data_schema):
        """Test searching commitments by entry count."""
        commitment_system.create_commitment(
            agent_id="agent1",
            data_schema=sample_data_schema,
            entry_count=100,
            data_hash="hash1"
        )
        commitment_system.create_commitment(
            agent_id="agent2",
            data_schema=sample_data_schema,
            entry_count=500,
            data_hash="hash2"
        )

        # Search for commitments with at least 200 entries
        results = commitment_system.search_commitments(min_entry_count=200)

        assert len(results) == 1
        assert results[0].entry_count == 500

    @pytest.mark.unit
    def test_search_commitments_with_zero_bounds(self, commitment_system, sample_data_schema):
        """min/max_entry_count=0 must be honored, not silently dropped.

        Regression: a truthy `if min_entry_count:` check would turn
        `max_entry_count=0` (a legitimate "only empty datasets" query) into
        a no-op. The implementation uses `is not None`.
        """
        commitment_system.create_commitment(
            agent_id="empty_agent",
            data_schema=sample_data_schema,
            entry_count=0,
            data_hash="hash_empty",
        )
        commitment_system.create_commitment(
            agent_id="nonempty_agent",
            data_schema=sample_data_schema,
            entry_count=100,
            data_hash="hash_nonempty",
        )

        # max_entry_count=0 means "only empty datasets".
        results = commitment_system.search_commitments(max_entry_count=0)
        assert len(results) == 1
        assert results[0].entry_count == 0

        # min_entry_count=0 is a no-op filter but must not crash.
        results = commitment_system.search_commitments(min_entry_count=0)
        assert len(results) == 2

    @pytest.mark.unit
    def test_search_commitments_by_coverage(self, commitment_system):
        """Test searching commitments by coverage area."""
        global_schema = DataSchema(
            structure=DataStructure.CUSTOMER_LIST,
            format=DataFormat.STRUCTURED,
            fields=["id"],
            metadata={"industry": "retail", "coverage_area": "global"}
        )
        commitment_system.create_commitment(
            agent_id="agent1",
            data_schema=global_schema,
            entry_count=100,
            data_hash="hash1"
        )

        regional_schema = DataSchema(
            structure=DataStructure.CUSTOMER_LIST,
            format=DataFormat.STRUCTURED,
            fields=["id"],
            metadata={"industry": "retail", "coverage_area": "regional"}
        )
        commitment_system.create_commitment(
            agent_id="agent2",
            data_schema=regional_schema,
            entry_count=50,
            data_hash="hash2"
        )

        # Search for global coverage
        results = commitment_system.search_commitments(coverage_area=CoverageArea.GLOBAL)

        assert len(results) == 1
        assert results[0].coverage_area == CoverageArea.GLOBAL

    @pytest.mark.unit
    def test_verify_commitment_integrity_success(self, commitment_system, sample_data_schema):
        """Test successful commitment integrity verification."""
        test_data = [
            {"name": "Alice", "email": "alice@example.com", "phone": "+1234567890"},
            {"name": "Bob", "email": "bob@example.com", "phone": "+0987654321"}
        ]

        # Create commitment with actual data hash
        data_hash = commitment_system._hash_data_content(test_data)
        commitment = commitment_system.create_commitment(
            agent_id="agent_test",
            data_schema=sample_data_schema,
            entry_count=len(test_data),
            data_hash=data_hash
        )

        # Verify integrity
        is_valid = commitment_system.verify_commitment_integrity(
            commitment.commitment_id, test_data
        )

        assert is_valid

    @pytest.mark.unit
    def test_verify_commitment_integrity_wrong_count(self, commitment_system, sample_data_schema):
        """Test integrity verification fails with wrong entry count."""
        test_data = [{"name": "Alice", "email": "alice@example.com", "phone": "+123"}]

        commitment = commitment_system.create_commitment(
            agent_id="agent_test",
            data_schema=sample_data_schema,
            entry_count=5,  # Wrong count
            data_hash="test_hash"
        )

        is_valid = commitment_system.verify_commitment_integrity(
            commitment.commitment_id, test_data
        )

        assert not is_valid

    @pytest.mark.unit
    def test_verify_commitment_integrity_wrong_hash(self, commitment_system, sample_data_schema):
        """Test integrity verification fails with wrong data hash."""
        test_data = [{"name": "Alice", "email": "alice@example.com", "phone": "+123"}]

        commitment = commitment_system.create_commitment(
            agent_id="agent_test",
            data_schema=sample_data_schema,
            entry_count=1,
            data_hash="wrong_hash"
        )

        is_valid = commitment_system.verify_commitment_integrity(
            commitment.commitment_id, test_data
        )

        assert not is_valid


class TestCommitmentCompatibilityChecker:
    """Test CommitmentCompatibilityChecker class."""

    @pytest.mark.unit
    def test_check_commitment_pair_compatibility_success(self, sample_commitment_metadata):
        """Test successful compatibility check between commitments."""
        commitment1 = sample_commitment_metadata
        commitment2 = CommitmentMetadata(
            commitment_id="commit_other",
            agent_id="agent_002",
            data_structure=DataStructure.CUSTOMER_LIST,  # Same
            data_format=DataFormat.STRUCTURED,  # Same
            entry_count=500,
            field_count=3,
            estimated_size_mb=1.5,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.DAILY,  # Same
            coverage_area=CoverageArea.GLOBAL,
            industry=Industry.RETAIL,  # Same
        )

        is_compatible, reason = CommitmentCompatibilityChecker.check_commitment_pair_compatibility(
            commitment1, commitment2
        )

        assert is_compatible
        assert "Compatible" in reason

    @pytest.mark.unit
    def test_check_commitment_pair_industry_mismatch_is_note(self, sample_commitment_metadata):
        """Industry mismatch should not be a hard blocker for generic compatibility."""
        commitment1 = sample_commitment_metadata
        commitment2 = CommitmentMetadata(
            commitment_id="commit_other",
            agent_id="agent_002",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.STRUCTURED,
            entry_count=500,
            field_count=3,
            estimated_size_mb=1.5,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.DAILY,
            coverage_area=CoverageArea.GLOBAL,
            industry=Industry.FINANCE,  # Different
        )

        is_compatible, reason = CommitmentCompatibilityChecker.check_commitment_pair_compatibility(
            commitment1, commitment2
        )

        assert is_compatible is True
        assert "industry differs" in reason.lower()

    @pytest.mark.unit
    def test_check_commitment_pair_incompatible_format(self, sample_commitment_metadata):
        """Test incompatibility due to format mismatch."""
        commitment1 = sample_commitment_metadata
        commitment2 = CommitmentMetadata(
            commitment_id="commit_other",
            agent_id="agent_002",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.UNSTRUCTURED,  # Different
            entry_count=500,
            field_count=3,
            estimated_size_mb=1.5,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.DAILY,
            coverage_area=CoverageArea.GLOBAL,
            industry=Industry.RETAIL,
        )

        is_compatible, reason = CommitmentCompatibilityChecker.check_commitment_pair_compatibility(
            commitment1, commitment2
        )

        assert not is_compatible
        assert "format mismatch" in reason.lower()

    @pytest.mark.unit
    def test_check_commitment_pair_different_structure_is_compatible(self, sample_commitment_metadata):
        """Core checker does not enforce structure equality — structure matching is protocol-specific.

        PSI legitimately pairs CUSTOMER_LIST (initiator) with BLACKLIST (receiver).
        Protocol implementations apply their own pairing rules on top of this generic checker.
        """
        commitment1 = sample_commitment_metadata
        commitment2 = CommitmentMetadata(
            commitment_id="commit_other",
            agent_id="agent_002",
            data_structure=DataStructure.BLACKLIST,  # Different — valid for PSI
            data_format=DataFormat.STRUCTURED,
            entry_count=500,
            field_count=3,
            estimated_size_mb=1.5,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.DAILY,
            coverage_area=CoverageArea.GLOBAL,
            industry=Industry.RETAIL,
        )

        is_compatible, reason = CommitmentCompatibilityChecker.check_commitment_pair_compatibility(
            commitment1, commitment2
        )

        # Industry, format, and freshness all match — core checker passes this pair.
        # Structure-level pairing rules belong in protocol implementations, not core.
        assert is_compatible

    @pytest.mark.unit
    def test_check_commitment_pair_incompatible_freshness(self, sample_commitment_metadata):
        """Test incompatibility due to stale data."""
        commitment1 = sample_commitment_metadata
        commitment2 = CommitmentMetadata(
            commitment_id="commit_other",
            agent_id="agent_002",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.STRUCTURED,
            entry_count=500,
            field_count=3,
            estimated_size_mb=1.5,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.WEEKLY,  # Not fresh enough
            coverage_area=CoverageArea.GLOBAL,
            industry=Industry.RETAIL,
        )

        is_compatible, reason = CommitmentCompatibilityChecker.check_commitment_pair_compatibility(
            commitment1, commitment2
        )

        assert not is_compatible
        assert "fresh" in reason.lower()

    @pytest.mark.unit
    def test_score_parameter_pair_compatibility_success(self, sample_commitment_metadata):
        """Test compatibility scoring with compatible parameters."""
        params1 = AP3ExtensionParameters(
            roles=["ap3_initiator"],
            supported_operations=["PSI"],
            commitments=[sample_commitment_metadata]
        )

        params2 = AP3ExtensionParameters(
            roles=["ap3_receiver"],
            supported_operations=["PSI"],
            commitments=[sample_commitment_metadata]
        )

        score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
            params1, params2
        )

        # Should get full score: 0.3 (roles) + 0.3 (operations) + 0.4 (commitments) = 1.0
        assert score == 1.0
        assert "PASS" in explanation

    @pytest.mark.unit
    def test_score_parameter_pair_incompatible_roles(self, sample_commitment_metadata):
        """Test compatibility scoring with incompatible roles."""
        params1 = AP3ExtensionParameters(
            roles=["ap3_initiator"],
            supported_operations=["PSI"],
            commitments=[sample_commitment_metadata]
        )

        params2 = AP3ExtensionParameters(
            roles=["ap3_initiator"],  # Both initiators
            supported_operations=["PSI"],
            commitments=[sample_commitment_metadata]
        )

        score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
            params1, params2
        )

        assert score == 0.0
        assert "incompatible" in explanation.lower()

    @pytest.mark.unit
    def test_score_parameter_pair_no_common_operations(self, sample_commitment_metadata):
        """Test compatibility scoring with no common operations."""
        params1 = AP3ExtensionParameters(
            roles=["ap3_initiator"],
            supported_operations=["PSI"],
            commitments=[sample_commitment_metadata]
        )

        params2 = AP3ExtensionParameters(
            roles=["ap3_receiver"],
            supported_operations=["PIR"],  # Different
            commitments=[sample_commitment_metadata]
        )

        score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
            params1, params2
        )

        # Should have role score but no operation score
        assert score == 0.3
        assert "No common operations" in explanation


class TestRemoteAgentDiscoveryService:
    """Test RemoteAgentDiscoveryService class."""

    @pytest.fixture
    def discovery_service(self):
        """Create a RemoteAgentDiscoveryService instance."""
        return RemoteAgentDiscoveryService()

    @pytest.mark.unit
    def test_initialization(self, discovery_service):
        """Test RemoteAgentDiscoveryService initialization."""
        assert len(discovery_service.agent_cards_cache) == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.requires_network
    async def test_fetch_agent_card_success(self, discovery_service, mock_agent_card):
        """Test successfully fetching an agent card."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_response = AsyncMock()
            mock_response.json.return_value = mock_agent_card
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            agent_url = "http://test-agent.example.com"
            card = await discovery_service.fetch_agent_card(agent_url)

            assert card is not None
            # we should use await to access the coroutine
            card_data = await card if hasattr(card, '__await__') else card
            assert card_data["name"] == "Test Agent"
            assert agent_url in discovery_service.agent_cards_cache

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fetch_agent_card_failure(self, discovery_service):
        """Test handling fetch failure."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.side_effect = Exception("Network error")
            mock_client_class.return_value = mock_client

            agent_url = "http://test-agent.example.com"
            card = await discovery_service.fetch_agent_card(agent_url)

            assert card is None

    @pytest.mark.unit
    def test_extract_ap3_params_success(self, discovery_service, mock_agent_card):
        """Test extracting AP3 parameters from agent card."""
        params = discovery_service.extract_ap3_params(mock_agent_card)

        assert params is not None
        assert "ap3_receiver" in params.roles
        assert "PSI" in params.supported_operations

    @pytest.mark.unit
    def test_extract_ap3_params_no_extensions(self, discovery_service):
        """Test extracting AP3 params from card without extensions."""
        card = {
            "name": "Test Agent",
            "capabilities": {}
        }

        params = discovery_service.extract_ap3_params(card)
        assert params is None

    @pytest.mark.unit
    def test_extract_ap3_params_no_ap3_extension(self, discovery_service):
        """Test extracting AP3 params from card without AP3 extension."""
        card = {
            "name": "Test Agent",
            "capabilities": {
                "extensions": [
                    {"uri": "http://other-extension.com", "params": {}}
                ]
            }
        }

        params = discovery_service.extract_ap3_params(card)
        assert params is None

    @pytest.mark.unit
    def test_format_compatibility_report_compatible(self, discovery_service):
        """Test formatting compatibility report for compatible agents."""
        report = discovery_service.format_compatibility_report(
            receiver_url="http://receiver.example.com",
            initiator_url="http://initiator.example.com",
            is_compatible=True,
            score=0.9,
            explanation="All checks passed",
            details={}
        )

        assert "COMPATIBLE" in report
        assert "✅" in report
        assert "0.90" in report

    @pytest.mark.unit
    def test_format_compatibility_report_incompatible(self, discovery_service):
        """Test formatting compatibility report for incompatible agents."""
        report = discovery_service.format_compatibility_report(
            receiver_url="http://receiver.example.com",
            initiator_url="http://initiator.example.com",
            is_compatible=False,
            score=0.3,
            explanation="Role mismatch",
            details={}
        )

        assert "INCOMPATIBLE" in report
        assert "❌" in report
        assert "0.30" in report
        assert "Role mismatch" in report
