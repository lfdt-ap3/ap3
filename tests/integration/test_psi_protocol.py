"""End-to-end PSI tests driving the 4-envelope flow directly.

Drives PSIOperation through start → receive → process → process without
involving the AP3 a2a wire layer, exactly as `run_intent` would.
"""

import base64

import pytest

from ap3_functions import PSIOperation
from ap3_functions.exceptions import ProtocolError
from ap3_functions.psi import SESSION_ID_SIZE, compute_session_id


# ---------------------------------------------------------------------------
# Helper: drive both sides through the full protocol
# ---------------------------------------------------------------------------

def _run_psi(customer_data: str, sanction_list: list[str]) -> bool:
    """Run a complete PSI exchange and return the match result.

    Wire order:
        OB.start          → init   (OB commits sid_0, hidden behind blind)
        BB.receive(init)  → msg0   (BB reveals sid_1)
        OB.process(msg0)  → msg1   (OB opens commit: sid_0 ‖ blind ‖ psc_msg1)
        BB.process(msg1)  → msg2
        OB.process(msg2)  → done, result
    """
    initiator = PSIOperation()
    receiver = PSIOperation()

    # OB opens the session.
    init_out = initiator.start(role="initiator", inputs={"customer_data": customer_data})
    ob_sid = init_out["session_id"]
    init_msg = init_out["outgoing"]
    assert init_msg["phase"] == "init"

    # BB receives the init kick-off and replies with msg0 (sid_1).
    msg0_out = receiver.receive(
        role="receiver",
        message=init_msg,
        config={"sanction_list": sanction_list},
    )
    bb_sid = msg0_out["session_id"]
    msg0 = msg0_out["outgoing"]
    assert msg0["phase"] == "msg0"

    # OB receives msg0 and emits msg1 = sid_0 || blind || psc_msg1.
    msg1_out = initiator.process(session_id=ob_sid, message=msg0)
    msg1 = msg1_out["outgoing"]
    assert msg1["phase"] == "msg1"

    # BB receives msg1, runs PSC, emits msg2.
    msg2_out = receiver.process(session_id=bb_sid, message=msg1)
    assert msg2_out["done"] is True
    msg2 = msg2_out["outgoing"]
    assert msg2["phase"] == "msg2"

    # OB finalizes.
    final = initiator.process(session_id=ob_sid, message=msg2)
    assert final["done"] is True
    return bool(final["result"]["is_match"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPSIProtocolFullExecution:
    """Test complete execution of the PSI protocol."""

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_customer_in_sanction_list(self, psi_test_data):
        is_match = _run_psi(
            psi_test_data["sanctioned_customer"],
            psi_test_data["sanction_list"],
        )
        assert is_match is True

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_customer_not_in_sanction_list(self, psi_test_data):
        is_match = _run_psi(
            psi_test_data["customer_data"],
            psi_test_data["sanction_list"],
        )
        assert is_match is False

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_empty_sanction_list_rejected(self, psi_test_data):
        """Receiver rejects empty sanction lists to prevent misconfiguration."""
        with pytest.raises(ProtocolError, match="sanction_list must be non-empty"):
            _run_psi(psi_test_data["customer_data"], [])

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_large_sanction_list(self):
        """100-entry list with the target injected at index 50."""
        customer_data = "Target Person,ID999,999 Test St"
        sanction_list = [f"Person{i},ID{i},{i} Street Ave" for i in range(100)]
        sanction_list[50] = customer_data

        assert _run_psi(customer_data, sanction_list) is True

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_case_sensitive_matching(self):
        customer_data = "John Doe,ID123,123 Main St"
        sanction_list = [
            "JOHN DOE,ID123,123 Main St",  # different case
            "Jane Smith,ID456,456 Oak Ave",
        ]
        assert _run_psi(customer_data, sanction_list) is False

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_multiple_independent_sessions(self, psi_test_data):
        sanction_list = psi_test_data["sanction_list"]
        assert _run_psi("Customer One,ID001,001 First St", sanction_list) is False
        assert _run_psi(psi_test_data["sanctioned_customer"], sanction_list) is True


class TestPSIProtocolSessionBinding:
    """Both parties must derive the same session_id from their halves."""

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_sid_contribution_changes_session_id_each_run(self, psi_test_data):
        """Two runs with the same inputs use different session_ids
        (sid_0 and sid_1 are fresh per run)."""
        sanction_list = psi_test_data["sanction_list"]
        customer = psi_test_data["sanctioned_customer"]

        sids_seen = set()
        for _ in range(3):
            initiator = PSIOperation()
            receiver = PSIOperation()
            init_out = initiator.start(role="initiator", inputs={"customer_data": customer})
            msg0_out = receiver.receive(
                role="receiver",
                message=init_out["outgoing"],
                config={"sanction_list": sanction_list},
            )
            sid_1 = base64.b64decode(msg0_out["outgoing"]["message"])
            msg1_out = initiator.process(
                session_id=init_out["session_id"], message=msg0_out["outgoing"]
            )
            payload = base64.b64decode(msg1_out["outgoing"]["message"])
            sid_0 = payload[:SESSION_ID_SIZE]
            assert len(sid_0) == SESSION_ID_SIZE
            assert len(sid_1) == SESSION_ID_SIZE
            sids_seen.add(compute_session_id(sid_0, sid_1))

            # Drive the rest of the protocol so receiver finishes cleanly.
            msg2_out = receiver.process(
                session_id=msg0_out["session_id"], message=msg1_out["outgoing"]
            )
            initiator.process(session_id=init_out["session_id"], message=msg2_out["outgoing"])

        assert len(sids_seen) == 3  # all distinct


class TestPSIProtocolErrorHandling:

    @pytest.mark.integration
    @pytest.mark.protocol
    def test_protocol_privacy_preservation(self, psi_test_data):
        """Protocol completes without revealing list contents."""
        is_match = _run_psi(
            "Unknown Person,ID000,000 Unknown St",
            psi_test_data["sanction_list"],
        )
        assert is_match is False

    def test_psi_operation_id(self):
        assert PSIOperation.operation_id == "protocol.psi.sanction.v1"

    def test_missing_customer_data_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="customer_data"):
            op.start(role="initiator", inputs={})

    def test_wrong_role_for_start_raises(self):
        op = PSIOperation()
        with pytest.raises(ProtocolError, match="initiator"):
            op.start(role="receiver", inputs={"customer_data": "test"})
