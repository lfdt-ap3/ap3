"""Unit tests for PSIOperation (ap3_functions/psi/operations.py).

Wire flow (4 envelopes, OB = initiator, BB = receiver):

    OB → BB : phase="init"  payload = commit(sid_0, blind)
    BB → OB : phase="msg0"  payload = sid_1
    OB → BB : phase="msg1"  payload = sid_0 ‖ blind ‖ psc_msg1
    BB → OB : phase="msg2"  payload = psc_msg2
"""

import base64
import pytest
from unittest.mock import patch

from ap3 import Operation, OperationResult
from ap3_functions import PSIOperation
from ap3_functions.exceptions import ProtocolError
from ap3_functions.psi import SESSION_ID_SIZE, HASH_SIZE, BLIND_VALUE_SIZE, create_commitment


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")


class TestPSIOperationInterface:
    """PSIOperation implements ap3.Operation correctly."""

    @pytest.mark.unit
    def test_is_operation_subclass(self):
        assert issubclass(PSIOperation, Operation)

    @pytest.mark.unit
    def test_operation_id(self):
        assert PSIOperation().operation_id == "protocol.psi.sanction.v1"

    @pytest.mark.unit
    def test_has_session_method(self):
        assert callable(PSIOperation().has_session)


class TestPSIOperationStart:
    """on_start (initiator) emits the wire-level init kick-off."""

    @pytest.mark.unit
    def test_start_wrong_role_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="only supported for role='initiator'"):
            op.start(role="receiver", inputs={"customer_data": "test"}, config={}, context={})

    @pytest.mark.unit
    def test_start_missing_customer_data_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="PSI requires customer_data"):
            op.start(role="initiator", inputs={}, config={}, context={})

    @pytest.mark.unit
    def test_start_emits_init_and_stashes_customer(self):
        op = PSIOperation()
        result = op.on_start(
            role="initiator",
            inputs={"customer_data": "John Doe,ID123"},
            config={},
            context={},
        )
        assert isinstance(result, OperationResult)
        assert result.done is False
        assert result.outgoing["phase"] == "init"
        commit = base64.b64decode(result.outgoing["message"])
        assert len(commit) == HASH_SIZE
        assert "sid_0" in result.next_state
        assert "blind_value" in result.next_state
        assert result.next_state["customer_data"] == "John Doe,ID123"


class TestPSIOperationReceiver:
    """on_process branches for role='receiver'."""

    @pytest.mark.unit
    def test_init_missing_sanction_list_raises(self):
        commit_b = b"1" * HASH_SIZE
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="sanction_list must be non-empty"):
            op.on_process(
                role="receiver",
                state={},
                message={"phase": "init", "message": _b64e(commit_b)},
                config={},
                context={},
            )

    @pytest.mark.unit
    def test_init_emits_msg0_with_sid1(self):
        with patch("ap3_functions.psi.operations.psi_ffi") as mock_ffi:
            commit_b = b"1" * HASH_SIZE
            mock_ffi.generate_hash.return_value = b"h" * 32
            op = PSIOperation()
            result = op.on_process(
                role="receiver",
                state={},
                message={"phase": "init", "message": _b64e(commit_b)},
                config={"sanction_list": ["person1", "person2"]},
                context={},
            )
            assert result.done is False
            assert result.outgoing["phase"] == "msg0"
            sid_1 = base64.b64decode(result.outgoing["message"])
            assert len(sid_1) == SESSION_ID_SIZE
            assert "commit" in result.next_state
            assert "sid_1" in result.next_state
            assert "sanction_hashes" in result.next_state
            assert len(result.next_state["sanction_hashes"]) == 2

    @pytest.mark.unit
    def test_msg1_unpacks_sid0_and_calls_psc(self):
        with patch("ap3_functions.psi.operations.psi_ffi") as mock_ffi:
            mock_ffi.compute_session_id.return_value = b"S" * 32
            mock_ffi.process_psc_msg1.return_value = b"psc_msg2"

            sid_1_b = b"1" * SESSION_ID_SIZE
            sid_0_b = b"0" * SESSION_ID_SIZE
            blind_value = b"2" * BLIND_VALUE_SIZE
            # Compute the commit from the real helper rather than hardcoding a
            # base64 string — keeps the test valid if COMMITMENT_LABEL changes.
            commit = _b64e(create_commitment(sid_0_b, blind_value))
            psc_msg1 = b"PSC_MSG1_bytes"

            op = PSIOperation()
            result = op.on_process(
                role="receiver",
                state={
                    "sid_1": _b64e(sid_1_b),
                    "commit": commit,
                    "sanction_hashes": [_b64e(b"h" * 32)],
                },
                message={"phase": "msg1", "message": _b64e(sid_0_b + blind_value + psc_msg1)},
                config={},
                context={},
            )

            mock_ffi.compute_session_id.assert_called_once_with(sid_0_b, sid_1_b)
            mock_ffi.process_psc_msg1.assert_called_once()
            call_args = mock_ffi.process_psc_msg1.call_args[0]
            assert call_args[0] == b"S" * 32       # session_id
            assert call_args[1] == psc_msg1        # psc_msg1 stripped of sid_0
            assert result.done is True
            assert result.outgoing == {"phase": "msg2", "message": _b64e(b"psc_msg2")}

    @pytest.mark.unit
    def test_msg1_short_payload_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="too short for sid_0"):
            op.on_process(
                role="receiver",
                state={
                    "commit": _b64e(b"0" * HASH_SIZE),
                    "sid_1": _b64e(b"1" * SESSION_ID_SIZE),
                    "sanction_hashes": [_b64e(b"h" * 32)],
                },
                message={"phase": "msg1", "message": _b64e(b"x" * (SESSION_ID_SIZE - 1))},
                config={},
                context={},
            )

    @pytest.mark.unit
    def test_msg1_missing_state_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="state is missing"):
            op.on_process(
                role="receiver",
                state={},
                message={"phase": "msg1", "message": _b64e(b"x" * 80)},
                config={},
                context={},
            )

    @pytest.mark.unit
    def test_receiver_unknown_phase_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="unexpected phase"):
            op.on_process(
                role="receiver",
                state={},
                message={"phase": "garbage"},
                config={"sanction_list": ["x"]},
                context={},
            )


class TestPSIOperationInitiator:
    """on_process branches for role='initiator'."""

    @pytest.mark.unit
    def test_msg0_generates_sid0_and_emits_msg1(self):
        with patch("ap3_functions.psi.operations.psi_ffi") as mock_ffi:
            mock_ffi.generate_hash.return_value = b"hash" * 8
            mock_ffi.compute_session_id.return_value = b"S" * 32
            mock_ffi.create_psc_msg1.return_value = (b"psc_state", b"PSC_MSG1")

            sid_1 = b"1" * SESSION_ID_SIZE
            op = PSIOperation()
            result = op.on_process(
                role="initiator",
                state={
                    "sid_0": _b64e(b"0" * SESSION_ID_SIZE),
                    "blind_value": _b64e(b"1" * HASH_SIZE),
                    "customer_data": "John Doe,ID123"
                },
                message={"phase": "msg0", "message": _b64e(sid_1)},
                config={},
                context={},
            )

            # compute_session_id called with (sid_0, sid_1); sid_0 was generated locally
            (sid_0_arg, sid_1_arg), _ = mock_ffi.compute_session_id.call_args
            assert sid_1_arg == sid_1
            assert len(sid_0_arg) == SESSION_ID_SIZE
            assert sid_0_arg != sid_1  # vanishingly unlikely to collide

            assert result.done is False
            assert result.outgoing["phase"] == "msg1"
            payload = base64.b64decode(result.outgoing["message"])
            assert payload[:SESSION_ID_SIZE] == sid_0_arg
            assert payload[SESSION_ID_SIZE+HASH_SIZE:] == b"PSC_MSG1"
            assert result.next_state == {"initiator_state": _b64e(b"psc_state")}

    @pytest.mark.unit
    def test_msg0_bad_sid1_length_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="sid_1 must be"):
            op.on_process(
                role="initiator",
                state={"customer_data": "X"},
                message={"phase": "msg0", "message": _b64e(b"short")},
                config={},
                context={},
            )

    @pytest.mark.unit
    def test_msg0_missing_customer_data_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="missing customer_data"):
            op.on_process(
                role="initiator",
                state={},
                message={"phase": "msg0", "message": _b64e(b"1" * SESSION_ID_SIZE)},
                config={},
                context={},
            )

    @pytest.mark.unit
    def test_msg2_calls_psc_finalize(self):
        with patch("ap3_functions.psi.operations.psi_ffi") as mock_ffi:
            mock_ffi.process_psc_msg2.return_value = True
            op = PSIOperation()
            result = op.on_process(
                role="initiator",
                state={"initiator_state": _b64e(b"psc_state")},
                message={"phase": "msg2", "message": _b64e(b"psc_msg2")},
                config={},
                context={},
            )
            mock_ffi.process_psc_msg2.assert_called_once_with(b"psc_state", b"psc_msg2")
            assert result.done is True
            assert result.result == {"is_match": True}

    @pytest.mark.unit
    def test_msg2_missing_state_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="state is missing"):
            op.on_process(
                role="initiator",
                state={},
                message={"phase": "msg2", "message": _b64e(b"x")},
                config={},
                context={},
            )

    @pytest.mark.unit
    def test_initiator_unknown_phase_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="unexpected phase"):
            op.on_process(
                role="initiator",
                state={"customer_data": "X"},
                message={"phase": "garbage"},
                config={},
                context={},
            )


class TestPSIConvenienceFunctions:
    """Public helpers stay importable."""

    @pytest.mark.unit
    def test_ffi_functions_accessible(self):
        from ap3_functions.psi import (
            SESSION_ID_SIZE,
            compute_session_id,
            create_psc_msg1,
            generate_hash,
            process_psc_msg1,
            process_psc_msg2,
        )
        assert callable(generate_hash)
        assert callable(create_psc_msg1)
        assert callable(process_psc_msg1)
        assert callable(process_psc_msg2)
        assert callable(compute_session_id)
        assert SESSION_ID_SIZE == 32

    @pytest.mark.unit
    def test_compute_session_id_is_deterministic_and_size_correct(self):
        from ap3_functions.psi import compute_session_id

        sid_0 = b"0" * SESSION_ID_SIZE
        sid_1 = b"1" * SESSION_ID_SIZE
        out_a = compute_session_id(sid_0, sid_1)
        out_b = compute_session_id(sid_0, sid_1)
        assert out_a == out_b
        assert len(out_a) == 32
        # Swapping order produces a different session_id (parties' roles matter).
        assert compute_session_id(sid_1, sid_0) != out_a

    @pytest.mark.unit
    def test_compute_session_id_rejects_wrong_size(self):
        from ap3_functions.psi import compute_session_id

        with pytest.raises(ValueError, match="sid must be"):
            compute_session_id(b"\x00" * (SESSION_ID_SIZE - 1), b"\x00" * SESSION_ID_SIZE)


# ---------------------------------------------------------------------------
# Scalar canonical check (security: blocks malleable DLogProof.s)
# ---------------------------------------------------------------------------

# Ristretto255 group order L = 2^252 + 27742317777372353535851937790883648493.
_RISTRETTO_L_INT = (1 << 252) + 27742317777372353535851937790883648493


class TestScalarCanonical:
    """`Scalar.from_bytes` must reject non-canonical (≥ L) scalars."""

    @pytest.mark.unit
    def test_canonical_scalar_accepted(self):
        from ap3_functions.psi.psi_internal.ristretto import Scalar

        s = Scalar.random()
        roundtripped = Scalar.from_bytes(s.value)
        assert roundtripped.value == s.value

    @pytest.mark.unit
    def test_non_canonical_scalar_rejected(self):
        from ap3_functions.psi.psi_internal.ristretto import Scalar

        # Smallest non-canonical: L itself (reduces to 0). And L+5.
        for offset in (0, 5, 100, (1 << 252) - 1):  # last is well past L
            bad = ((_RISTRETTO_L_INT + offset) % (1 << 256)).to_bytes(32, "little")
            with pytest.raises(ValueError, match="Invalid scalar"):
                Scalar.from_bytes(bad)

    @pytest.mark.unit
    def test_zero_scalar_rejected(self):
        from ap3_functions.psi.psi_internal.ristretto import Scalar

        with pytest.raises(ValueError, match="Invalid scalar"):
            Scalar.from_bytes(b"\x00" * 32)

    @pytest.mark.unit
    def test_wrong_length_rejected(self):
        from ap3_functions.psi.psi_internal.ristretto import Scalar

        with pytest.raises(ValueError, match="Invalid scalar"):
            Scalar.from_bytes(b"\x01" * 31)
        with pytest.raises(ValueError, match="Invalid scalar"):
            Scalar.from_bytes(b"\x01" * 33)

    @pytest.mark.unit
    def test_boundary_l_minus_one_accepted(self):
        """L-1 is the largest valid canonical scalar."""
        from ap3_functions.psi.psi_internal.ristretto import Scalar

        max_canonical = (_RISTRETTO_L_INT - 1).to_bytes(32, "little")
        s = Scalar.from_bytes(max_canonical)
        assert s.value == max_canonical
