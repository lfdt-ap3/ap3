"""Unit tests for AP3 directive types (ap3/types/directive.py)."""

import pytest
from datetime import datetime, timezone
import uuid

from ap3.types.directive import (
    PrivacyIntentDirective,
    PrivacyResultDirective,
    PrivacyError,
    PrivacyViolationError,
    PRIVACY_INTENT_DIRECTIVE_DATA_KEY,
    PRIVACY_RESULT_DIRECTIVE_DATA_KEY,
)
from ap3.signing.primitives import generate_keypair


class TestPrivacyIntentDirective:
    """Test PrivacyIntentDirective model."""

    @pytest.mark.unit
    def test_create_privacy_intent_directive(self, sample_privacy_intent_directive):
        """Test creating a PrivacyIntentDirective."""
        assert sample_privacy_intent_directive.operation_type == "PSI"
        assert len(sample_privacy_intent_directive.participants) == 2
        assert sample_privacy_intent_directive.signature is None

    @pytest.mark.unit
    def test_validate_directive_success(self, sample_privacy_intent_directive):
        """Test successful validation of PrivacyIntentDirective."""
        is_valid, error = sample_privacy_intent_directive.validate_directive()

        assert is_valid
        assert error is None

    @pytest.mark.unit
    def test_validate_directive_insufficient_participants(self, sample_session_id, future_time):
        """Test validation fails with insufficient participants."""
        # Pydantic validates on construction, so this should raise ValidationError
        with pytest.raises(Exception) as exc_info:  # Catches pydantic ValidationError
            PrivacyIntentDirective(
                ap3_session_id=sample_session_id,
                intent_directive_id=str(uuid.uuid4()),
                operation_type="PSI",
                participants=["http://single-agent.example.com"],  # Only 1 participant
                expiry=future_time.isoformat()
            )
        
        # Verify it's a validation error about participants
        assert "participants" in str(exc_info.value).lower() or "2 items" in str(exc_info.value)

    @pytest.mark.unit
    def test_validate_directive_expired(self, sample_session_id, past_time):
        """Test validation fails with expired directive."""
        directive = PrivacyIntentDirective(
            ap3_session_id=sample_session_id,
            intent_directive_id=str(uuid.uuid4()),
            operation_type="PSI",
            participants=["http://agent1.example.com", "http://agent2.example.com"],
            nonce="nonce_test",
            payload_hash="0" * 64,
            expiry=past_time.isoformat()
        )

        is_valid, error = directive.validate_directive()

        assert not is_valid
        assert "expired" in error.lower()

    @pytest.mark.unit
    def test_validate_directive_invalid_operation(self, sample_session_id, future_time):
        """Test validation fails with invalid operation type."""
        # Pydantic validates on construction, so this should raise ValidationError
        with pytest.raises(Exception) as exc_info:  # Catches pydantic ValidationError
            PrivacyIntentDirective(
                ap3_session_id=sample_session_id,
                intent_directive_id=str(uuid.uuid4()),
                operation_type="INVALID_OP",  # Invalid operation
                participants=["http://agent1.example.com", "http://agent2.example.com"],
                expiry=future_time.isoformat()
            )
        
        # Verify it's a validation error about operation_type
        assert "operation_type" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()

    @pytest.mark.unit
    def test_is_expired_future_time(self, sample_privacy_intent_directive):
        """Test is_expired returns False for future expiry."""
        assert not sample_privacy_intent_directive.is_expired()

    @pytest.mark.unit
    def test_is_expired_past_time(self, sample_session_id, past_time):
        """Test is_expired returns True for past expiry."""
        directive = PrivacyIntentDirective(
            ap3_session_id=sample_session_id,
            intent_directive_id=str(uuid.uuid4()),
            operation_type="PSI",
            participants=["http://agent1.example.com", "http://agent2.example.com"],
            nonce="nonce_test",
            payload_hash="0" * 64,
            expiry=past_time.isoformat()
        )

        assert directive.is_expired()

    @pytest.mark.unit
    def test_is_expired_invalid_timestamp(self, sample_session_id):
        """Test is_expired returns True for invalid timestamp."""
        directive = PrivacyIntentDirective(
            ap3_session_id=sample_session_id,
            intent_directive_id=str(uuid.uuid4()),
            operation_type="PSI",
            participants=["http://agent1.example.com", "http://agent2.example.com"],
            nonce="nonce_test",
            payload_hash="0" * 64,
            expiry="invalid_timestamp"
        )

        # Should treat invalid timestamp as expired for safety
        assert directive.is_expired()

    @pytest.mark.unit
    def test_sign_and_verify_signature_roundtrip(self, sample_privacy_intent_directive):
        """sign()/verify_signature() should round-trip for a generated keypair."""
        private_key, public_key = generate_keypair()
        directive = sample_privacy_intent_directive.model_copy()
        directive.signature = directive.sign(private_key)
        assert directive.verify_signature(public_key) is True

    @pytest.mark.unit
    def test_verify_signature_false_when_missing(self, sample_privacy_intent_directive):
        """verify_signature() returns False when signature is absent."""
        _, public_key = generate_keypair()
        directive = sample_privacy_intent_directive.model_copy(update={"signature": None})
        assert directive.verify_signature(public_key) is False


class TestPrivacyResultDirective:
    """Test PrivacyResultDirective model."""

    @pytest.mark.unit
    def test_create_privacy_result_directive(self, sample_privacy_result_directive):
        """Test creating a PrivacyResultDirective."""
        assert sample_privacy_result_directive.ap3_session_id is not None
        assert sample_privacy_result_directive.result_data is not None
        assert sample_privacy_result_directive.proofs is not None

    @pytest.mark.unit
    def test_validate_directive_success(self, sample_privacy_result_directive):
        """Test successful validation of result directive."""
        is_valid, error = sample_privacy_result_directive.validate_directive()

        assert is_valid
        assert error is None

    @pytest.mark.unit
    def test_validate_directive_missing_result_hash(
        self, sample_session_id, sample_operation_proofs
    ):
        """Test validation fails with missing result hash."""
        from ap3.types.core import ResultData

        result_data = ResultData(
            encoded_result="abc123",
            result_hash="",  # Empty hash
            metadata={}
        )

        directive = PrivacyResultDirective(
            ap3_session_id=sample_session_id,
            result_directive_id=str(uuid.uuid4()),
            result_data=result_data,
            proofs=sample_operation_proofs,
            attestation="experimental_placeholders",
        )

        is_valid, error = directive.validate_directive()

        assert not is_valid
        assert "result hash" in error.lower()

    @pytest.mark.unit
    def test_validate_directive_missing_correctness_proof(
        self, sample_session_id, sample_result_data
    ):
        """Test validation fails with missing correctness proof."""
        from ap3.types.core import OperationProofs

        proofs = OperationProofs(
            correctness_proof="",  # Empty proof
            privacy_proof="proof123",
            verification_proof="proof456"
        )

        directive = PrivacyResultDirective(
            ap3_session_id=sample_session_id,
            result_directive_id=str(uuid.uuid4()),
            result_data=sample_result_data,
            proofs=proofs,
            attestation="experimental_placeholders",
        )

        is_valid, error = directive.validate_directive()

        assert not is_valid
        assert "correctness proof" in error.lower()

    @pytest.mark.unit
    def test_validate_directive_missing_privacy_proof(
        self, sample_session_id, sample_result_data
    ):
        """Test validation fails with missing privacy proof."""
        from ap3.types.core import OperationProofs

        proofs = OperationProofs(
            correctness_proof="proof123",
            privacy_proof="",  # Empty proof
            verification_proof="proof456"
        )

        directive = PrivacyResultDirective(
            ap3_session_id=sample_session_id,
            result_directive_id=str(uuid.uuid4()),
            result_data=sample_result_data,
            proofs=proofs,
            attestation="experimental_placeholders",
        )

        is_valid, error = directive.validate_directive()

        assert not is_valid
        assert "privacy proof" in error.lower()

    @pytest.mark.unit
    def test_sign_and_verify_signature_roundtrip(self, sample_privacy_result_directive):
        """Result directive sign()/verify_signature() should round-trip."""
        private_key, public_key = generate_keypair()
        directive = sample_privacy_result_directive.model_copy()
        directive.signature = directive.sign(private_key)
        assert directive.verify_signature(public_key) is True

    @pytest.mark.unit
    def test_verify_proofs_refused_for_placeholders(self, sample_privacy_result_directive):
        """Placeholder attestation must refuse verify_proofs() loudly."""
        # The fixture builds a directive with attestation="experimental_placeholders".
        # Any call to verify_proofs() must reject it before hitting the
        # NotImplementedError stub — otherwise an integrator could mis-read
        # placeholder proofs as cryptographically attested.
        with pytest.raises(ValueError, match="experimental_placeholders"):
            sample_privacy_result_directive.verify_proofs()


class TestPrivacyError:
    """Test PrivacyError model."""

    @pytest.mark.unit
    def test_create_privacy_error(self):
        """Test creating a PrivacyError."""
        error = PrivacyError(
            error_code="TIMEOUT",
            error_message="Operation timed out",
            operation_type="PSI",
            recovery_options=["Retry", "Use cached result"]
        )

        assert error.error_code == "TIMEOUT"
        assert error.error_message == "Operation timed out"
        assert len(error.recovery_options) == 2
        assert error.timestamp is not None

    @pytest.mark.unit
    def test_privacy_error_default_timestamp(self):
        """Test that PrivacyError has default timestamp."""
        error = PrivacyError(
            error_code="TEST",
            error_message="Test error"
        )

        # Should have a timestamp
        assert error.timestamp is not None
        # Should be recent (within last minute)
        error_time = datetime.fromisoformat(error.timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        time_diff = (now - error_time).total_seconds()
        assert time_diff < 60  # Less than 60 seconds old

class TestPrivacyViolationError:
    """Test PrivacyViolationError model."""

    @pytest.mark.unit
    def test_create_privacy_violation_error(self):
        """Test creating a PrivacyViolationError."""
        error = PrivacyViolationError(
            error_code="DATA_LEAK",
            error_message="Unauthorized data revealed",
            violation_type="information_disclosure",
            allowed_reveal="aggregate_count",
            actual_reveal="individual_records"
        )

        assert error.error_code == "DATA_LEAK"
        assert error.violation_type == "information_disclosure"
        assert error.allowed_reveal == "aggregate_count"
        assert error.actual_reveal == "individual_records"
        assert error.timestamp is not None

    @pytest.mark.unit
    def test_privacy_violation_default_timestamp(self):
        """Test that PrivacyViolationError has default timestamp."""
        error = PrivacyViolationError(
            error_code="TEST",
            error_message="Test violation",
            violation_type="test",
            allowed_reveal="none",
            actual_reveal="all"
        )

        # Should have a timestamp
        assert error.timestamp is not None
        # Should be recent
        error_time = datetime.fromisoformat(error.timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        time_diff = (now - error_time).total_seconds()
        assert time_diff < 60


class TestDirectiveConstants:
    """Test directive data key constants."""

    @pytest.mark.unit
    def test_data_key_constants(self):
        """Test that data key constants are defined."""
        assert PRIVACY_INTENT_DIRECTIVE_DATA_KEY == "ap3.directives.PrivacyIntentDirective"
        assert PRIVACY_RESULT_DIRECTIVE_DATA_KEY == "ap3.directives.PrivacyResultDirective"
