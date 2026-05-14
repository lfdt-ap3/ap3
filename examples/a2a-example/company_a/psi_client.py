#!/usr/bin/env python3
"""Initiate AP3 PSI from Company A to Company B.

Run:
- Terminal 1: `cd examples/a2a-example/company_b && uv run .`
- Terminal 2: `cd examples/a2a-example/company_a && uv run .`
- Terminal 3: `cd examples/a2a-example/company_a && uv run psi_client.py`
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ap3.a2a import AP3Identity, AP3Middleware, attach_ap3_extension
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
from ap3_functions import PSIOperation

from db import fetch_default_customer, fetch_customer_list

def _load_keys(path: Path) -> tuple[bytes, bytes]:
    raw = json.loads(path.read_text())
    return bytes.fromhex(raw["private_key_hex"]), bytes.fromhex(raw["public_key_hex"])


async def main() -> None:
    private_key, public_key = _load_keys(Path(__file__).parent / "ap3_keys.json")
    db_path = Path(__file__).parent / "data" / "initiator.db"
    customer_list = fetch_customer_list(db_path)

    # This card must match what the running Company A server is serving
    # (especially the public key), because Company B will fetch it to verify
    # the intent signature.
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface

    card = AgentCard(
        name="Company A",
        description="Hello world + AP3 initiator",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
    )
    _card_url = os.getenv("CARD_URL", "http://localhost:10002")
    card.supported_interfaces.append(
        AgentInterface(protocol_binding="JSONRPC", url=_card_url)
    )

    commitment = CommitmentMetadata(
        agent_id="company_a_customers",
        commitment_id="customers_v1",
        data_structure=DataStructure.CUSTOMER_LIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=len(customer_list),
        field_count=3,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )
    attach_ap3_extension(
        card,
        roles=["ap3_initiator"],
        supported_operations=["PSI"],
        commitments=[commitment],
        public_key=public_key,
    )

    ap3 = AP3Middleware(
        identity=AP3Identity(
            card=card,
            card_url=_card_url,
            private_key=private_key,
            public_key=public_key,
            role="ap3_initiator",
            operation_type="PSI",
        ),
        operation=PSIOperation(),
    )

    result = await ap3.run_intent(
        peer_url=os.getenv("COMPANY_B_URL", "http://localhost:10003"),
        inputs={"customer_data": fetch_default_customer(db_path)},
    )
    print("PSI result:", result.result_data.metadata["description"])


if __name__ == "__main__":
    asyncio.run(main())

