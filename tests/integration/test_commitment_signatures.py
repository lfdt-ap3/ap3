"""Live agents on ports 19140-19145.

Remember keeps the context it was given. inputs['send'] is the only path that puts an envelope on the wire.
"""

from datetime import datetime, timezone

import pytest
from sse_starlette.sse import AppStatus

from ap3 import Operation, OperationResult
from ap3.a2a.agent import PrivacyAgent
from ap3.services.commitment import CommitmentMetadataSystem
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


def tampered(commitment, private_key):
    signed = commitment.model_copy(
        update={"signature": CommitmentMetadataSystem.sign_commitment(commitment, private_key)}
    )
    return signed.model_copy(update={"entry_count": signed.entry_count + 1})


class Remember(Operation):
    operation_id = "proposal.remember"
    operation_type = "PSI"

    def __init__(self):
        super().__init__()
        self.contexts = []
        self.received = False

    def on_start(self, role, inputs, config, context):
        self.contexts.append(context)
        if inputs.get("send"):
            return OperationResult(next_state={}, outgoing={"phase": "ping", "message": "hi"})
        return OperationResult(done=True, result={"ok": True})

    def on_process(self, role, state, message, config, context):
        if role == "receiver":
            self.received = True
            return OperationResult(done=True, outgoing={"phase": "pong", "message": "hi"})
        return OperationResult(done=True, result={"ok": True})


def agent(name, port, role, operation, private_key, public_key, structure, bad=False):
    meta = commitment(name, structure)
    if bad:
        meta = tampered(meta, private_key)
    return PrivacyAgent(
        name=name,
        description=name,
        card_url=f"http://localhost:{port}",
        host="localhost",
        port=port,
        role=role,
        operation=operation,
        commitment=meta,
        private_key=private_key,
        public_key=public_key,
        allow_private_initiator_urls=True,
    )


@pytest.mark.asyncio
async def test_honest_card_verifies_and_is_handed_to_the_operation():
    """Given two honest cards. When A runs one intent. Then the operation sees C's signed commitment."""
    remember = Remember()
    asking = agent("agent_a", 19140, "ap3_initiator", remember, *generate_keypair(), DataStructure.CUSTOMER_LIST)
    answering = agent("agent_c", 19141, "ap3_receiver", Remember(), *generate_keypair(), DataStructure.BLACKLIST)
    async with asking.serving(), answering.serving():
        result = await asking.run_intent(peer_url="http://localhost:19141", inputs={})
    assert result.result_data is not None
    seen = remember.contexts[0]["peer_commitments"][0]
    assert seen.agent_id == "agent_c"
    assert seen.signature


@pytest.mark.asyncio
async def test_changed_peer_commitment_is_refused_before_sending():
    """Given C's card signed, then entry_count bumped. When A calls run_intent. Then COMMITMENT_SIGNATURE_INVALID, and C is not entered."""
    receiver_op = Remember()
    asking = agent("agent_a", 19142, "ap3_initiator", Remember(), *generate_keypair(), DataStructure.CUSTOMER_LIST)
    answering = agent(
        "agent_c", 19143, "ap3_receiver", receiver_op, *generate_keypair(), DataStructure.BLACKLIST, bad=True
    )
    async with asking.serving(), answering.serving():
        with pytest.raises(PrivacyProtocolError) as caught:
            await asking.run_intent(peer_url="http://localhost:19143", inputs={})
    assert caught.value.error.error_code == "COMMITMENT_SIGNATURE_INVALID"
    assert receiver_op.received is False


@pytest.mark.asyncio
async def test_changed_initiator_commitment_is_refused_by_the_receiver():
    """Given A's card signed, then entry_count bumped. When A sends one envelope. Then C refuses, and C's operation is not entered."""
    receiver_op = Remember()
    asking = agent(
        "agent_a", 19144, "ap3_initiator", Remember(), *generate_keypair(), DataStructure.CUSTOMER_LIST, bad=True
    )
    answering = agent("agent_c", 19145, "ap3_receiver", receiver_op, *generate_keypair(), DataStructure.BLACKLIST)
    async with asking.serving(), answering.serving():
        with pytest.raises(PrivacyProtocolError) as caught:
            await asking.run_intent(peer_url="http://localhost:19145", inputs={"send": True})
    assert caught.value.error.error_code == "COMMITMENT_SIGNATURE_INVALID"
    assert receiver_op.received is False
