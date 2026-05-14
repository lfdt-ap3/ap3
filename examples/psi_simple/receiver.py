"""Minimal AP3 PSI receiver over A2A.

Holds a sanction list in memory, serves an AgentCard so peers can fetch
its AP3 public key, and reacts to inbound PSI msg1 envelopes.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

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

from db import fetch_sanction_list

async def main(port: int, host: str, public_url: str) -> None:
    sanction_list = fetch_sanction_list(Path(__file__).parent / "data" / "receiver.db")
    private_key, public_key = generate_keypair()
    commitment = CommitmentMetadata(
        agent_id="bank_b_sanctions",
        commitment_id="sanctions_v1",
        data_structure=DataStructure.BLACKLIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=len(sanction_list),
        field_count=3,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.REAL_TIME,
        industry=Industry.FINANCE,
    )

    agent = PrivacyAgent(
        name="PSI Receiver",
        description="Holds a sanction list; performs PSI on request",
        card_url=public_url,
        host=host,
        port=port,
        role="ap3_receiver",
        operation=PSIOperation(),
        commitment=commitment,
        private_key=private_key,
        public_key=public_key,
        receiver_config_provider=lambda: {"sanction_list": sanction_list},
        # Dev quickstart: initiator advertises a loopback card URL.
        allow_private_initiator_urls=True,
    )

    async with agent.serving():
        print(f"[receiver] serving on {public_url} (bind {host}:{port})")
        print(f"[receiver] sanction list entries: {len(sanction_list)}")
        await agent.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=10003)
    parser.add_argument("--host", default="localhost", help="Bind address")
    parser.add_argument(
        "--public-url",
        default=None,
        help="URL peers should use to reach this agent (defaults to http://<host>:<port>)",
    )
    args = parser.parse_args()
    public_url = args.public_url or f"http://{args.host}:{args.port}"
    asyncio.run(main(args.port, args.host, public_url))
