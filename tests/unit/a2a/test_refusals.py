import pytest

from ap3.a2a.agent import PrivacyAgent
from ap3.a2a.wire import ProtocolEnvelope
from ap3.signing.primitives import generate_keypair
from ap3.types import (
    CommitmentMetadata,
    DataFormat,
    DataFreshness,
    DataStructure,
    Industry,
)
from ap3_functions import PSIOperation


def _one_commitment() -> CommitmentMetadata:
    from datetime import datetime, timezone

    return CommitmentMetadata(
        agent_id="test_agent",
        commitment_id="commit_v1",
        data_structure=DataStructure.CUSTOMER_LIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=1,
        field_count=1,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )


@pytest.mark.asyncio
async def test_receiver_refuses_intent_not_addressed_to_self(monkeypatch):
    priv, pub = generate_keypair()
    agent = PrivacyAgent(
        name="rx",
        description="rx",
        card_url="http://localhost:9999",
        host="localhost",
        port=9999,
        role="ap3_receiver",
        operation=PSIOperation(),
        commitment=_one_commitment(),
        private_key=priv,
        public_key=pub,
    )

    async def _resolve_peer(url: str, *, force_refresh: bool = False):
        raise AssertionError("resolve_peer should not be called for wrong receiver")

    monkeypatch.setattr(agent._core._peer_client, "resolve_peer", _resolve_peer)

    env = ProtocolEnvelope(
        operation=agent._core._operation.operation_id,
        phase="msg1",
        session_id="sid",
        payload="hello",
        privacy_intent={
            "ap3_session_id": "sid",
            "intent_directive_id": "id",
            "operation_type": "PSI",
            # Doesn't include receiver URL ("http://localhost:9999")
            "participants": ["http://initiator.example", "http://someone-else.example"],
            "expiry": "2999-01-01T00:00:00+00:00",
            "signature": "AA==",
        },
    )

    reply = await agent.handle_envelope(env)
    assert reply is not None
    assert reply.error is not None
    assert reply.error["error_code"] == "WRONG_RECEIVER"

