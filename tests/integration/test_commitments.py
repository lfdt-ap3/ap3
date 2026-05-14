"""Integration tests for commitment chains and compatibility."""

import pytest

from ap3.services import (
    CommitmentMetadataSystem,
    CommitmentCompatibilityChecker,
)
from ap3.types import (
    DataStructure,
    DataFormat,
    CoverageArea,
    DataSchema,
    AP3ExtensionParameters,
)


class TestCommitmentChains:
    """Test commitment creation and verification chains."""

    @pytest.mark.integration
    def test_create_multiple_commitments_and_search(self, sample_data_schema):
        """Test creating multiple commitments and searching through them."""
        system = CommitmentMetadataSystem()

        # Create commitments for different agents
        system.create_commitment(
            agent_id="agent_retail_1",
            data_schema=sample_data_schema,
            entry_count=1000,
            data_hash="hash1"
        )

        retail_schema = DataSchema(
            structure=DataStructure.CUSTOMER_LIST,
            format=DataFormat.STRUCTURED,
            fields=["customer_id", "name"],
            metadata={"industry": "retail", "coverage_area": "regional"}
        )
        system.create_commitment(
            agent_id="agent_retail_2",
            data_schema=retail_schema,
            entry_count=500,
            data_hash="hash2"
        )

        finance_schema = DataSchema(
            structure=DataStructure.FINANCIAL_RECORDS,
            format=DataFormat.STRUCTURED,
            fields=["account_id", "balance"],
            metadata={"industry": "finance", "coverage_area": "global"}
        )
        system.create_commitment(
            agent_id="agent_finance_1",
            data_schema=finance_schema,
            entry_count=2000,
            data_hash="hash3"
        )

        # Search for retail commitments
        retail_results = system.search_commitments(
            data_structure=DataStructure.CUSTOMER_LIST
        )
        assert len(retail_results) == 2

        # Search for large datasets
        large_results = system.search_commitments(min_entry_count=1000)
        assert len(large_results) == 2

        # Search for regional coverage
        regional_results = system.search_commitments(coverage_area=CoverageArea.REGIONAL)
        assert len(regional_results) == 1

    @pytest.mark.integration
    def test_commitment_integrity_verification_chain(self):
        """Test verifying integrity of multiple commitments."""
        system = CommitmentMetadataSystem()

        # Create test data
        data1 = [
            {"name": "Alice", "email": "alice@example.com", "phone": "+1111111111"},
            {"name": "Bob", "email": "bob@example.com", "phone": "+2222222222"}
        ]

        data2 = [
            {"name": "Charlie", "email": "charlie@example.com", "phone": "+3333333333"}
        ]

        schema = DataSchema(
            structure=DataStructure.CUSTOMER_LIST,
            format=DataFormat.STRUCTURED,
            fields=["name", "email", "phone"],
            metadata={"industry": "retail", "coverage_area": "global"}
        )

        # Create commitments
        hash1 = system._hash_data_content(data1)
        c1 = system.create_commitment(
            agent_id="agent1",
            data_schema=schema,
            entry_count=len(data1),
            data_hash=hash1
        )

        hash2 = system._hash_data_content(data2)
        c2 = system.create_commitment(
            agent_id="agent2",
            data_schema=schema,
            entry_count=len(data2),
            data_hash=hash2
        )

        # Verify both commitments
        assert system.verify_commitment_integrity(c1.commitment_id, data1)
        assert system.verify_commitment_integrity(c2.commitment_id, data2)

        # Verify cross-verification fails
        assert not system.verify_commitment_integrity(c1.commitment_id, data2)
        assert not system.verify_commitment_integrity(c2.commitment_id, data1)


class TestCommitmentCompatibilityWorkflow:
    """Test end-to-end commitment compatibility checking."""

    @pytest.mark.integration
    def test_compatible_agents_full_workflow(self):
        """Test full workflow of checking compatible agents."""
        system = CommitmentMetadataSystem()

        # Agent 1: Retail supplier
        supplier_schema = DataSchema(
            structure=DataStructure.SUPPLY_CHAIN_DATA,
            format=DataFormat.STRUCTURED,
            fields=["product_id", "quantity", "price"],
            metadata={"industry": "manufacturing", "coverage_area": "global"}
        )
        supplier_commitment = system.create_commitment(
            agent_id="supplier_agent",
            data_schema=supplier_schema,
            entry_count=500,
            data_hash="supplier_hash"
        )
        supplier_metadata = system.get_public_metadata(supplier_commitment.commitment_id)

        supplier_params = AP3ExtensionParameters(
            roles=["ap3_initiator"],
            supported_operations=["PSI"],
            commitments=[supplier_metadata]
        )

        # Agent 2: Manufacturer
        manufacturer_schema = DataSchema(
            structure=DataStructure.SUPPLY_CHAIN_DATA,
            format=DataFormat.STRUCTURED,
            fields=["component_id", "specs"],
            metadata={"industry": "manufacturing", "coverage_area": "global"}
        )
        manufacturer_commitment = system.create_commitment(
            agent_id="manufacturer_agent",
            data_schema=manufacturer_schema,
            entry_count=300,
            data_hash="manufacturer_hash"
        )
        manufacturer_metadata = system.get_public_metadata(manufacturer_commitment.commitment_id)

        manufacturer_params = AP3ExtensionParameters(
            roles=["ap3_receiver"],
            supported_operations=["PSI"],
            commitments=[manufacturer_metadata]
        )

        # Check compatibility
        score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
            supplier_params, manufacturer_params
        )

        assert score == 1.0  # Full compatibility
        assert "PASS" in explanation

    @pytest.mark.integration
    def test_incompatible_agents_full_workflow(self):
        """Test full workflow of checking incompatible agents."""
        system = CommitmentMetadataSystem()

        # Agent 1: Retail
        retail_schema = DataSchema(
            structure=DataStructure.CUSTOMER_LIST,
            format=DataFormat.STRUCTURED,
            fields=["customer_id"],
            metadata={"industry": "retail", "coverage_area": "global"}
        )
        retail_commitment = system.create_commitment(
            agent_id="retail_agent",
            data_schema=retail_schema,
            entry_count=1000,
            data_hash="retail_hash"
        )
        retail_metadata = system.get_public_metadata(retail_commitment.commitment_id)

        retail_params = AP3ExtensionParameters(
            roles=["ap3_initiator"],
            supported_operations=["PSI"],
            commitments=[retail_metadata]
        )

        # Agent 2: Finance (different industry)
        finance_schema = DataSchema(
            structure=DataStructure.FINANCIAL_RECORDS,
            format=DataFormat.STRUCTURED,
            fields=["account_id"],
            metadata={"industry": "finance", "coverage_area": "global"}
        )
        finance_commitment = system.create_commitment(
            agent_id="finance_agent",
            data_schema=finance_schema,
            entry_count=500,
            data_hash="finance_hash"
        )
        finance_metadata = system.get_public_metadata(finance_commitment.commitment_id)

        finance_params = AP3ExtensionParameters(
            roles=["ap3_receiver"],
            supported_operations=["PSI"],
            commitments=[finance_metadata]
        )

        # Check compatibility
        score, explanation = CommitmentCompatibilityChecker.score_parameter_pair_compatibility(
            retail_params, finance_params, operation_type="PSI"
        )

        # Should have roles + operations but fail on commitments
        assert score < 1.0
        assert "PSI requires" in explanation
