import uvicorn

from starlette.applications import Starlette
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from a2a.utils.constants import DEFAULT_RPC_URL
from agent_executor import (
    HelloWorldAgentExecutor,  # type: ignore[import-untyped]
)

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from ap3.a2a import AP3Identity, AP3Middleware, PrivacyAgentExecutor, attach_ap3_extension
from ap3.signing.primitives import generate_keypair
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
from ap3_functions import PSIOperation

from db import fetch_customer_list


def _load_or_create_keys(path: Path) -> tuple[bytes, bytes]:
    if path.exists():
        raw = json.loads(path.read_text())
        return bytes.fromhex(raw["private_key_hex"]), bytes.fromhex(raw["public_key_hex"])
    private_key, public_key = generate_keypair()
    path.write_text(
        json.dumps(
            {"private_key_hex": private_key.hex(), "public_key_hex": public_key.hex()},
            indent=2,
        )
    )
    return private_key, public_key


if __name__ == '__main__':
    # --8<-- [start:AgentSkill]
    skill = AgentSkill(
        id='hello_world',
        name='Returns hello world',
        description='just returns hello world',
        tags=['hello world'],
        examples=['hi', 'hello world'],
    )
    # --8<-- [end:AgentSkill]

    extended_skill = AgentSkill(
        id='super_hello_world',
        name='Returns a SUPER Hello World',
        description='A more enthusiastic greeting, only for authenticated users.',
        tags=['hello world', 'super', 'extended'],
        examples=['super hi', 'give me a super hello'],
    )

    _self_url = os.getenv("CARD_URL", "http://localhost:10002")

    # --8<-- [start:AgentCard]
    # This will be the public-facing agent card
    public_agent_card = AgentCard(
        name='Hello World Agent',
        description='Just a hello world agent',
        icon_url=f'{_self_url}/',
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(
            streaming=True, extended_agent_card=True
        ),
        supported_interfaces=[
            AgentInterface(
                protocol_binding='JSONRPC',
                url=_self_url,
            )
        ],
        skills=[skill],  # Only the basic skill for the public card
    )
    # --8<-- [end:AgentCard]

    # This will be the authenticated extended agent card
    # It includes the additional 'extended_skill'
    specific_extended_agent_card = AgentCard(
        name='Hello World Agent - Extended Edition',
        description='The full-featured hello world agent for authenticated users.',
        icon_url=f'{_self_url}/',
        version='1.0.1',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(
            streaming=True, extended_agent_card=True
        ),
        supported_interfaces=[
            AgentInterface(
                protocol_binding='JSONRPC',
                url=_self_url,
            )
        ],
        skills=[
            skill,
            extended_skill,
        ],  # Both skills for the extended card
    )

    # ------------------------------------------------------------------
    # Step: Add AP3 middleware (initiator)
    # ------------------------------------------------------------------
    private_key, public_key = _load_or_create_keys(Path(__file__).parent / "ap3_keys.json")

    customer_list = fetch_customer_list(Path(__file__).parent / "data" / "initiator.db")

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
        public_agent_card,
        roles=["ap3_initiator"],
        supported_operations=["PSI"],
        commitments=[commitment],
        public_key=public_key,
    )
    attach_ap3_extension(
        specific_extended_agent_card,
        roles=["ap3_initiator"],
        supported_operations=["PSI"],
        commitments=[commitment],
        public_key=public_key,
    )

    identity = AP3Identity(
        card=public_agent_card,
        card_url=_self_url,
        private_key=private_key,
        public_key=public_key,
        role="ap3_initiator",
        operation_type="PSI",
    )
    ap3 = AP3Middleware(identity=identity, operation=PSIOperation())

    executor = PrivacyAgentExecutor(protocol_handler=ap3, llm_executor=HelloWorldAgentExecutor())

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
        extended_agent_card=specific_extended_agent_card,
    )

    app = Starlette(routes=[
        *create_agent_card_routes(public_agent_card),
        *create_jsonrpc_routes(request_handler, rpc_url=DEFAULT_RPC_URL),
    ])

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "10002")))
