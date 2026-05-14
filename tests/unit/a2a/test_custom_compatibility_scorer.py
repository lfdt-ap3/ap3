from datetime import datetime, timezone

import pytest

from ap3.a2a import AP3Identity, AP3Middleware, attach_ap3_extension
from ap3.services import CommitmentCompatibilityChecker
from ap3.signing.primitives import generate_keypair
from ap3.types import (
    AP3ExtensionParameters,
    CommitmentMetadata,
    DataFormat,
    DataFreshness,
    DataStructure,
    Industry,
    PrivacyProtocolError,
)
from ap3_functions import PSIOperation
from a2a.types import AgentCapabilities, AgentCard, AgentInterface


def _card(url: str) -> AgentCard:
    c = AgentCard(
        name="x",
        description="x",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
    )
    c.supported_interfaces.append(AgentInterface(url=url, protocol_binding="JSONRPC"))
    return c


@pytest.mark.unit
def test_custom_compatibility_scorer_can_refuse_peer():
    private_key, public_key = generate_keypair()
    commitment = CommitmentMetadata(
        agent_id="a",
        commitment_id="c1",
        data_structure=DataStructure.CUSTOMER_LIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=1,
        field_count=1,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.OTHER,
    )

    card = _card("http://localhost:1234")
    attach_ap3_extension(
        card,
        roles=["ap3_initiator"],
        supported_operations=["PSI"],
        commitments=[commitment],
        public_key=public_key,
    )
    mw = AP3Middleware(
        identity=AP3Identity(
            card=card,
            card_url="http://localhost:1234",
            private_key=private_key,
            public_key=public_key,
            role="ap3_initiator",
            operation_type="PSI",
        ),
        operation=PSIOperation(),
        compatibility_scorer=lambda own, peer, op: (0.0, "nope"),
    )

    # Call the internal method directly to avoid network setup in a unit test.
    dummy_peer = type(
        "Peer",
        (),
        {"ap3_params": AP3ExtensionParameters(roles=["ap3_receiver"], supported_operations=["PSI"], commitments=[])},
    )()

    with pytest.raises(PrivacyProtocolError):
        mw._core._assert_compatible(  # type: ignore[attr-defined]
            dummy_peer
        )


def test_min_score_constant_is_used():
    assert CommitmentCompatibilityChecker.MIN_COMPAT_SCORE == 0.7

