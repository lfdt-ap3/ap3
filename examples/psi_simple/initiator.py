"""Minimal AP3 PSI initiator over A2A.

Serves its own AgentCard (so peers can verify its signatures), fetches
the receiver's card, runs the full PSI round-trip, and prints the
returned PrivacyResultDirective metadata.
"""

import argparse
import asyncio
from datetime import datetime, timezone

from ap3.a2a import PrivacyAgent
from ap3.signing.primitives import generate_keypair
from ap3.types import (
    CommitmentMetadata,
    DataFormat,
    DataFreshness,
    DataStructure,
    Industry,
)
from ap3_functions import PSIOperation


async def main(port: int, host: str, public_url: str, receiver_url: str, customer: str) -> None:
    private_key, public_key = generate_keypair()
    commitment = CommitmentMetadata(
        agent_id="bank_a_customers",
        commitment_id="customers_v1",
        data_structure=DataStructure.CUSTOMER_LIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=1,
        field_count=3,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )

    agent = PrivacyAgent(
        name="PSI Initiator",
        description="Checks customers against partner sanction lists",
        card_url=public_url,
        host=host,
        port=port,
        role="ap3_initiator",
        operation=PSIOperation(),
        commitment=commitment,
        private_key=private_key,
        public_key=public_key,
    )

    async with agent.serving():
        print(f"[initiator] serving on {public_url} (bind {host}:{port})")
        print(f"[initiator] checking '{customer}' against {receiver_url}")

        result = await agent.run_intent(
            peer_url=receiver_url,
            inputs={"customer_data": customer},
        )

        print()
        print("=" * 72)
        print(f"result directive id: {result.result_directive_id}")
        print(f"session id:          {result.ap3_session_id[:16]}...")
        print(f"result (raw):        {result.result_data.metadata['description']}")
        print(f"result hash:         {result.result_data.result_hash[:16]}...")
        print(f"signed:              {bool(result.signature)}")
        print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=10002)
    parser.add_argument("--host", default="localhost", help="Bind address")
    parser.add_argument(
        "--public-url",
        default=None,
        help="URL peers should use to reach this agent (defaults to http://<host>:<port>)",
    )
    parser.add_argument("--receiver", default="http://localhost:10003")
    parser.add_argument(
        "--customer",
        default="Joe Quimby,S4928374,213 Church St",
        help="Customer row to check; included in the sanction list by default",
    )
    args = parser.parse_args()
    public_url = args.public_url or f"http://{args.host}:{args.port}"
    asyncio.run(main(args.port, args.host, public_url, args.receiver, args.customer))
