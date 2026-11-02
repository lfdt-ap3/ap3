"""Live agents on ports 19169-19172."""

from datetime import datetime, timezone

import pytest
from sse_starlette.sse import AppStatus

from ap3 import Operation, OperationRefusal, OperationResult
from ap3.a2a.agent import PrivacyAgent
from ap3.signing.primitives import generate_keypair
from ap3.types import (
    CommitmentMetadata,
    DataFormat,
    DataFreshness,
    DataStructure,
    Industry,
    PrivacyProtocolError,
)


@pytest.fixture(autouse=True)
def fresh_sse_status(monkeypatch):
    # Process-wide. A server stopped with a stream open leaves it True, and later streams close at once.
    monkeypatch.setattr(AppStatus, "should_exit", False)


def commitment(agent_id, structure):
    return CommitmentMetadata(
        agent_id=agent_id,
        commitment_id=f"{agent_id}_data",
        data_structure=structure,
        data_format=DataFormat.STRUCTURED,
        entry_count=6,
        field_count=1,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )


class Ping(Operation):
    operation_id = "proposal.ping"
    operation_type = "PSI"

    def on_start(self, role, inputs, config, context):
        return OperationResult(next_state={}, outgoing={"phase": "ping", "message": "hi"})

    def on_process(self, role, state, message, config, context):
        return OperationResult(done=True, result={"ok": True})


class FailOnReceive(Ping):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def on_process(self, role, state, message, config, context):
        raise self.error


def agent(name, port, role, operation, private_key, public_key, structure):
    return PrivacyAgent(
        name=name,
        description=name,
        card_url=f"http://localhost:{port}",
        host="localhost",
        port=port,
        role=role,
        operation=operation,
        commitment=commitment(name, structure),
        private_key=private_key,
        public_key=public_key,
        allow_private_initiator_urls=True,
    )


@pytest.mark.asyncio
async def test_operation_refusal_reaches_the_initiator_with_its_code():
    """Given C's operation raises OperationRefusal PERIOD_ROLLING. When A asks. Then A gets PERIOD_ROLLING and C's message, not OPERATION_ERROR."""
    asking = agent("agent_a", 19169, "ap3_initiator", Ping(), *generate_keypair(), DataStructure.CUSTOMER_LIST)
    answering = agent(
        "agent_c", 19170, "ap3_receiver",
        FailOnReceive(OperationRefusal("PERIOD_ROLLING", "new period list in 5s")),
        *generate_keypair(), DataStructure.BLACKLIST,
    )
    async with asking.serving(), answering.serving():
        with pytest.raises(PrivacyProtocolError) as caught:
            await asking.run_intent(peer_url="http://localhost:19170", inputs={})
    assert caught.value.error.error_code == "PERIOD_ROLLING"
    assert caught.value.error.error_message == "new period list in 5s"


@pytest.mark.asyncio
async def test_any_other_operation_error_stays_generic():
    """Given C's operation raises ValueError with internal detail. When A asks. Then A gets OPERATION_ERROR, and the detail does not leave C."""
    asking = agent("agent_a", 19171, "ap3_initiator", Ping(), *generate_keypair(), DataStructure.CUSTOMER_LIST)
    answering = agent(
        "agent_c", 19172, "ap3_receiver", FailOnReceive(ValueError("db password rejected")),
        *generate_keypair(), DataStructure.BLACKLIST,
    )
    async with asking.serving(), answering.serving():
        with pytest.raises(PrivacyProtocolError) as caught:
            await asking.run_intent(peer_url="http://localhost:19172", inputs={})
    assert caught.value.error.error_code == "OPERATION_ERROR"
    assert "password" not in caught.value.error.error_message


def test_refusal_code_must_be_upper_snake_case():
    """Given a lowercase or overlong code. When OperationRefusal is built. Then ValueError."""
    with pytest.raises(ValueError):
        OperationRefusal("period rolling")
    with pytest.raises(ValueError):
        OperationRefusal("A" * 65)
