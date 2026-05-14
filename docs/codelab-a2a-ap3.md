---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Codelab: Sanctions check via Middleware (Advanced)</strong></h1>

---

**Estimated time:** 20 minutes

This codelab walks you through building two A2A-enabled agents from scratch, then layering AP3 as middleware to run PSI over SQLite-backed data. This is a lower level integration method that gives maximum flexibility.

- **Consumer agent (initiator)**: holds a **customer list** and initiates a PSI check
- **Provider agent (receiver)**: holds a **sanction list** and answers PSI requests

You’ll start with a plain A2A “hello world” style server, then layer **AP3** in as **middleware** so the same server can handle:

- Ordinary A2A requests (“hello world” text)
- AP3 PSI protocol envelopes (privacy-preserving computation)

!!! info
    For a faster, out-of-the-box integration, take a look at the [**AP3 PrivacyAgent**](./codelab-privacy-agent.md) codelab

---

## What you'll build

- **Consumer agent server** at `http://localhost:10002`
- **Provider agent server** at `http://localhost:10003`
- Two SQLite databases: customer list and sanction list

A completed PSI operation returns **match found / no match** as the outcome.

## Prerequisites

- Python **3.11–3.13**
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)

---

## Step 1: Create the project layout

From the **repo root**, create the folder structure:

```bash
mkdir -p my-a2a-agents/consumer my-a2a-agents/provider
```

```
my-a2a-agents/
  consumer/
  provider/
```

All commands in the rest of this codelab are run from the **repo root** (the directory that contains `my-a2a-agents/`).

### Root `pyproject.toml` (uv workspace)

Add a workspace manifest at the **repo root** (next to `my-a2a-agents/`):

```toml
[project]
name = "my-a2a-agents"
version = "0.1.0"
requires-python = ">=3.11,<3.14"

[tool.uv.workspace]
members = [
  "my-a2a-agents/consumer",
  "my-a2a-agents/provider",
]
```

---

## Step 2: Create `Consumer` A2A server

The baseline A2A server has three parts:

- an **AgentExecutor** that writes task events (status + artifacts)
- an **AgentCard** that advertises the agent metadata and skills
- an HTTP server that hosts:
    - agent-card routes
    - JSON-RPC routes (A2A transport)

### 2.1 Define the project

Create `my-a2a-agents/consumer/pyproject.toml`:

```toml
[project]
name = "consumer-agent"
version = "0.1.0"
description = "Consumer A2A agent (Hello World + AP3 initiator)"
requires-python = ">=3.11,<3.14"
dependencies = [
  "a2a-sdk[http-server]>=1.0.2",
  "httpx>=0.28.1",
  "pydantic>=2.11.4",
  "starlette>=0.46.2",
  "uvicorn>=0.34.2",
]

[tool.hatch.build.targets.wheel]
packages = ["."]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 2.2 Create the AgentExecutor

The `AgentExecutor` is the core logic of how an A2A agent processes requests and generates responses. The A2A Python SDK provides an abstract base class `a2a.server.agent_execution.AgentExecutor` that you implement, with two primary methods:

- `async def execute(self, context: RequestContext, event_queue: EventQueue)`: Handles incoming requests that expect a response or a stream of events. It processes the user's input (available via `context`) and uses the `event_queue` to send back `Message`, `Task`, `TaskStatusUpdateEvent`, or `TaskArtifactUpdateEvent` objects.
- `async def cancel(self, context: RequestContext, event_queue: EventQueue)`: Handles requests to cancel an ongoing task.

The `RequestContext` provides information about the incoming request, such as the user's message and any existing task details. The `EventQueue` is used by the executor to send events back to the client.

Create `my-a2a-agents/consumer/agent_executor.py`:

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.helpers.proto_helpers import new_task, new_text_artifact, new_text_message

class HelloWorldAgent:
    async def invoke(self) -> str:
        return "Hello, World!"

class HelloWorldAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.agent = HelloWorldAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task = context.current_task or new_task(
            task_id=context.task_id,
            context_id=context.context_id,
            state=TaskState.TASK_STATE_SUBMITTED,
        )
        await event_queue.enqueue_event(task)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=new_text_message("Processing request..."),
                ),
            )
        )

        result = await self.agent.invoke()

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="result", text=result),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported")
```

### 2.3 Create the baseline A2A server

The [Agent Card](https://a2a-protocol.org/latest/tutorials/python/3-agent-skills-and-card/) is a JSON document served at `.well-known/agent-card.json` — it's the agent's digital business card. `A2AStarletteApplication` wires up the card and JSON-RPC routes using [Starlette](https://www.starlette.io/) and [Uvicorn](https://www.uvicorn.org/).

Create `my-a2a-agents/consumer/__main__.py`:

```python
import os

import uvicorn
from starlette.applications import Starlette

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import DEFAULT_RPC_URL

from agent_executor import HelloWorldAgentExecutor

def main() -> None:
    skill = AgentSkill(
        id="hello_world",
        name="Returns hello world",
        description="just returns hello world",
        tags=["hello world"],
        examples=["hi", "hello world"],
    )

    self_url = os.getenv("CARD_URL", "http://localhost:10002")

    public_agent_card = AgentCard(
        name="Hello World Agent",
        description="Just a hello world agent",
        icon_url=f"{self_url}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=self_url),
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=HelloWorldAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
        extended_agent_card=None,
    )

    app = Starlette(
        routes=[
            *create_agent_card_routes(public_agent_card),
            *create_jsonrpc_routes(request_handler, rpc_url=DEFAULT_RPC_URL),
        ]
    )

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "10002")),
    )

if __name__ == "__main__":
    main()
```

**Verify it runs:**

```bash
uv lock
uv sync --package consumer-agent
uv run --package consumer-agent python my-a2a-agents/consumer/__main__.py
```

You should see:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10002 (Press CTRL+C to quit)
```

`Ctrl+C` to stop, then continue.

---

### 2.4 Add the SQLite database

Create `my-a2a-agents/consumer/db.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          row TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.commit()

def seed_if_empty(conn: sqlite3.Connection, rows: Iterable[str]) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM customer_entries").fetchone() or (0,)
    if count:
        return
    conn.executemany("INSERT OR IGNORE INTO customer_entries(row) VALUES (?)", [(r,) for r in rows])
    conn.commit()

def fetch_customer_list(db_path: Path) -> list[str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        seed_if_empty(conn, ["Joe Quimby,S4928374,213 Church St"])
        cur = conn.execute("SELECT row FROM customer_entries ORDER BY id ASC")
        return [r for (r,) in cur.fetchall()]
    finally:
        conn.close()

def fetch_default_customer(db_path: Path) -> str:
    rows = fetch_customer_list(db_path)
    if not rows:
        raise RuntimeError("No customers in database")
    return rows[0]
```

Add the DB trigger to `my-a2a-agents/consumer/__main__.py`. At the top of the file add:

```python
from pathlib import Path
from db import fetch_customer_list
```

And at the top of `main()`:

```python
def main() -> None:
    fetch_customer_list(Path(__file__).parent / "data" / "initiator.db")
    ...
```

**Verify the database:**

Start the server and wait for the startup message, then `Ctrl+C` to stop:

```bash
uv run --package consumer-agent python my-a2a-agents/consumer/__main__.py
```

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10002 (Press CTRL+C to quit)
```

`Ctrl+C`, then query the DB:

```bash
sqlite3 my-a2a-agents/consumer/data/initiator.db "SELECT id, row FROM customer_entries ORDER BY id;"
```

Expected output:

```
1|Joe Quimby,S4928374,213 Church St
```

---

### 2.5 Integrate AP3 middleware

Install AP3 for the Consumer:

```bash
uv add --package consumer-agent "ap3[a2a]" ap3-functions
```

AP3 middleware works in two lanes on the same server:

- **A2A lane** — your existing agent executor handles ordinary requests as usual
- **AP3 lane** — the middleware detects AP3-specific envelopes inside `Part.data` and routes them to the PSI operation

#### 2.5.1 Generate an Ed25519 identity keypair

Each server needs a persistent Ed25519 keypair to sign [AP3 directives](https://ap3-protocol.org/directives/). Add a loader helper and the required imports to `my-a2a-agents/consumer/__main__.py`:

```python
import json
from datetime import datetime, timezone
from ap3.signing.primitives import generate_keypair
```

Add this helper above `main()`:

```python
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
```

!!! info
    For simplicity this codelab generates a new keypair each run. In production you would always load from a persisted file.

#### 2.5.2 Advertise AP3 support via the Agent Card

Add the AP3 extension imports:

```python
from ap3.a2a import attach_ap3_extension
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
```

Inside `main()`, after `public_agent_card = AgentCard(...)`, load keys, build a commitment describing the customer dataset, and attach the extension. The `customer_list = fetch_customer_list(...)` line below replaces the standalone `fetch_customer_list(...)` call you added in Step 2.4 — we now need the returned list to populate `entry_count`:

```python
private_key, public_key = _load_or_create_keys(Path(__file__).parent / "ap3_keys.json")
customer_list = fetch_customer_list(Path(__file__).parent / "data" / "initiator.db")

commitment = CommitmentMetadata(
    agent_id="consumer_customers",
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
```

#### 2.5.3 Create the AP3 middleware and wrap the executor

Add the middleware imports:

```python
from ap3.a2a import AP3Identity, AP3Middleware, PrivacyAgentExecutor
from ap3_functions import PSIOperation
```

After `attach_ap3_extension`, create the identity and middleware:

```python
identity = AP3Identity(
    card=public_agent_card,
    card_url=self_url,
    private_key=private_key,
    public_key=public_key,
    role="ap3_initiator",
    operation_type="PSI",
)
ap3 = AP3Middleware(identity=identity, operation=PSIOperation())
```

Then replace the `DefaultRequestHandler` block:

```python
# Before
request_handler = DefaultRequestHandler(
    agent_executor=HelloWorldAgentExecutor(),
    ...
)

# After
executor = PrivacyAgentExecutor(protocol_handler=ap3, llm_executor=HelloWorldAgentExecutor())

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=InMemoryTaskStore(),
    agent_card=public_agent_card,
    extended_agent_card=None,
)
```

### 2.6 Complete Consumer `__main__.py`

Here is the full resulting file:

```python
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import DEFAULT_RPC_URL

from agent_executor import HelloWorldAgentExecutor

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

def main() -> None:
    skill = AgentSkill(
        id="hello_world",
        name="Returns hello world",
        description="just returns hello world",
        tags=["hello world"],
        examples=["hi", "hello world"],
    )

    self_url = os.getenv("CARD_URL", "http://localhost:10002")

    public_agent_card = AgentCard(
        name="Hello World Agent",
        description="Just a hello world agent",
        icon_url=f"{self_url}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=self_url)],
        skills=[skill],
    )

    private_key, public_key = _load_or_create_keys(Path(__file__).parent / "ap3_keys.json")
    customer_list = fetch_customer_list(Path(__file__).parent / "data" / "initiator.db")

    commitment = CommitmentMetadata(
        agent_id="consumer_customers",
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

    identity = AP3Identity(
        card=public_agent_card,
        card_url=self_url,
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
        extended_agent_card=None,
    )

    app = Starlette(
        routes=[
            *create_agent_card_routes(public_agent_card),
            *create_jsonrpc_routes(request_handler, rpc_url=DEFAULT_RPC_URL),
        ]
    )

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "10002")))

if __name__ == "__main__":
    main()
```

**Verify the Consumer starts cleanly:**

```bash
uv lock
uv sync --package consumer-agent
uv run --package consumer-agent python my-a2a-agents/consumer/__main__.py
```

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10002 (Press CTRL+C to quit)
```

`Ctrl+C` to stop. Consumer is complete — move on to the Provider.

---

## Step 3: Build the Provider Agent

Now, we build the Provider using the exact same pattern. The differences are: port `10003`, role `ap3_receiver`, a sanction list instead of a customer list, and passing the sanction data into the middleware.

### 3.1 Define the project

Create `my-a2a-agents/provider/pyproject.toml`:

```toml
[project]
name = "provider-agent"
version = "0.1.0"
description = "Provider A2A agent (Hello World + AP3 receiver)"
requires-python = ">=3.11,<3.14"
dependencies = [
  "a2a-sdk[http-server]>=1.0.2",
  "httpx>=0.28.1",
  "pydantic>=2.11.4",
  "starlette>=0.46.2",
  "uvicorn>=0.34.2",
]

[tool.hatch.build.targets.wheel]
packages = ["."]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 3.2 Create the AgentExecutor

Copy the executor from Consumer, as it is identical.

```bash
cp my-a2a-agents/consumer/agent_executor.py my-a2a-agents/provider/agent_executor.py
```

### 3.3 Create the baseline A2A server

Create `my-a2a-agents/provider/__main__.py` — same structure as Consumer, with port `10003`:

```python
import os

import uvicorn
from starlette.applications import Starlette

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import DEFAULT_RPC_URL

from agent_executor import HelloWorldAgentExecutor

def main() -> None:
    skill = AgentSkill(
        id="hello_world",
        name="Returns hello world",
        description="just returns hello world",
        tags=["hello world"],
        examples=["hi", "hello world"],
    )

    self_url = os.getenv("CARD_URL", "http://localhost:10003")

    public_agent_card = AgentCard(
        name="Hello World Agent",
        description="Just a hello world agent",
        icon_url=f"{self_url}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=self_url),
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=HelloWorldAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
        extended_agent_card=None,
    )

    app = Starlette(
        routes=[
            *create_agent_card_routes(public_agent_card),
            *create_jsonrpc_routes(request_handler, rpc_url=DEFAULT_RPC_URL),
        ]
    )

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "10003")),
    )

if __name__ == "__main__":
    main()
```

**Verify it runs:**

```bash
uv sync --package provider-agent
uv run --package provider-agent python my-a2a-agents/provider/__main__.py
```

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10003 (Press CTRL+C to quit)
```

`Ctrl+C` to stop, then continue.

---

### 3.4 Add the SQLite database

Create `my-a2a-agents/provider/db.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sanction_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          row TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.commit()

def seed_if_empty(conn: sqlite3.Connection, rows: Iterable[str]) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM sanction_entries").fetchone() or (0,)
    if count:
        return
    conn.executemany("INSERT OR IGNORE INTO sanction_entries(row) VALUES (?)", [(r,) for r in rows])
    conn.commit()

def fetch_sanction_list(db_path: Path) -> list[str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        seed_if_empty(
            conn,
            [
                "Joe Quimby,S4928374,213 Church St",
                "C. Montgomery Burns,S9283746,1000 Mammon Lane",
                "Bob Johnson,C3456789,789 Pine Street",
            ],
        )
        cur = conn.execute("SELECT row FROM sanction_entries ORDER BY id ASC")
        return [r for (r,) in cur.fetchall()]
    finally:
        conn.close()
```

Add the DB trigger to `my-a2a-agents/provider/__main__.py`:

```python
from pathlib import Path
from db import fetch_sanction_list
```

And at the top of `main()`:

```python
def main() -> None:
    fetch_sanction_list(Path(__file__).parent / "data" / "receiver.db")
    ...
```

**Verify the database:**

Start the server and wait for the startup message, then `Ctrl+C` to stop:

```bash
uv run --package provider-agent python my-a2a-agents/provider/__main__.py
```

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10003 (Press CTRL+C to quit)
```

`Ctrl+C`, then query the DB:

```bash
sqlite3 my-a2a-agents/provider/data/receiver.db "SELECT id, row FROM sanction_entries ORDER BY id;"
```

Expected output:

```
1|Joe Quimby,S4928374,213 Church St
2|C. Montgomery Burns,S9283746,1000 Mammon Lane
3|Bob Johnson,C3456789,789 Pine Street
```

---

### 3.5 Integrate AP3 middleware

Install AP3 for the Provider:

```bash
uv add --package provider-agent "ap3[a2a]" ap3-functions
```

#### 3.5.1 Generate an Ed25519 identity keypair

Add imports to `my-a2a-agents/provider/__main__.py`:

```python
import json
from datetime import datetime, timezone
from ap3.signing.primitives import generate_keypair
```

Add the helper above `main()`:

```python
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
```

#### 3.5.2 Advertise AP3 support via the Agent Card

Add imports:

```python
from ap3.a2a import attach_ap3_extension
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
```

Inside `main()`, after `public_agent_card = AgentCard(...)`. The `sanction_list = fetch_sanction_list(...)` line below replaces the standalone `fetch_sanction_list(...)` call you added in Step 3.4 — we now need the returned list to populate `entry_count` and to pass into the middleware:

```python
private_key, public_key = _load_or_create_keys(Path(__file__).parent / "ap3_keys.json")
sanction_list = fetch_sanction_list(Path(__file__).parent / "data" / "receiver.db")

commitment = CommitmentMetadata(
    agent_id="provider_sanctions",
    commitment_id="sanctions_v1",
    data_structure=DataStructure.BLACKLIST,
    data_format=DataFormat.STRUCTURED,
    entry_count=len(sanction_list),
    field_count=3,
    estimated_size_mb=0.001,
    last_updated=datetime.now(timezone.utc).isoformat(),
    data_freshness=DataFreshness.DAILY,
    industry=Industry.FINANCE,
)

attach_ap3_extension(
    public_agent_card,
    roles=["ap3_receiver"],
    supported_operations=["PSI"],
    commitments=[commitment],
    public_key=public_key,
)
```

#### 3.5.3 Create the AP3 middleware and wrap the executor

Add imports:

```python
from ap3.a2a import AP3Identity, AP3Middleware, PrivacyAgentExecutor
from ap3_functions import PSIOperation
```

After `attach_ap3_extension`:

```python
identity = AP3Identity(
    card=public_agent_card,
    card_url=self_url,
    private_key=private_key,
    public_key=public_key,
    role="ap3_receiver",
    operation_type="PSI",
)
ap3 = AP3Middleware(
    identity=identity,
    operation=PSIOperation(),
    receiver_config_provider=lambda: {"sanction_list": sanction_list},
    # Dev-only: consumer advertises a loopback card URL. Remove in production —
    # the SSRF guard will otherwise refuse the consumer's localhost initiator URL.
    allow_private_initiator_urls=True,
)
```

Replace the `DefaultRequestHandler` block:

```python
executor = PrivacyAgentExecutor(protocol_handler=ap3, llm_executor=HelloWorldAgentExecutor())

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=InMemoryTaskStore(),
    agent_card=public_agent_card,
    extended_agent_card=None,
)
```

### 3.6 Complete Provider `__main__.py`

Here is the full resulting file:

```python
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import DEFAULT_RPC_URL

from agent_executor import HelloWorldAgentExecutor

from ap3.a2a import AP3Identity, AP3Middleware, PrivacyAgentExecutor, attach_ap3_extension
from ap3.signing.primitives import generate_keypair
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
from ap3_functions import PSIOperation

from db import fetch_sanction_list

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

def main() -> None:
    skill = AgentSkill(
        id="hello_world",
        name="Returns hello world",
        description="just returns hello world",
        tags=["hello world"],
        examples=["hi", "hello world"],
    )

    self_url = os.getenv("CARD_URL", "http://localhost:10003")

    public_agent_card = AgentCard(
        name="Hello World Agent",
        description="Just a hello world agent",
        icon_url=f"{self_url}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=self_url)],
        skills=[skill],
    )

    private_key, public_key = _load_or_create_keys(Path(__file__).parent / "ap3_keys.json")
    sanction_list = fetch_sanction_list(Path(__file__).parent / "data" / "receiver.db")

    commitment = CommitmentMetadata(
        agent_id="provider_sanctions",
        commitment_id="sanctions_v1",
        data_structure=DataStructure.BLACKLIST,
        data_format=DataFormat.STRUCTURED,
        entry_count=len(sanction_list),
        field_count=3,
        estimated_size_mb=0.001,
        last_updated=datetime.now(timezone.utc).isoformat(),
        data_freshness=DataFreshness.DAILY,
        industry=Industry.FINANCE,
    )

    attach_ap3_extension(
        public_agent_card,
        roles=["ap3_receiver"],
        supported_operations=["PSI"],
        commitments=[commitment],
        public_key=public_key,
    )

    identity = AP3Identity(
        card=public_agent_card,
        card_url=self_url,
        private_key=private_key,
        public_key=public_key,
        role="ap3_receiver",
        operation_type="PSI",
    )
    ap3 = AP3Middleware(
        identity=identity,
        operation=PSIOperation(),
        receiver_config_provider=lambda: {"sanction_list": sanction_list},
        # Dev-only: consumer advertises a loopback card URL. Remove in production.
        allow_private_initiator_urls=True,
    )

    executor = PrivacyAgentExecutor(protocol_handler=ap3, llm_executor=HelloWorldAgentExecutor())

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=public_agent_card,
        extended_agent_card=None,
    )

    app = Starlette(
        routes=[
            *create_agent_card_routes(public_agent_card),
            *create_jsonrpc_routes(request_handler, rpc_url=DEFAULT_RPC_URL),
        ]
    )

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "10003")))

if __name__ == "__main__":
    main()
```

**Verify the Provider starts cleanly:**

```bash
uv lock
uv sync --package provider-agent
uv run --package provider-agent python my-a2a-agents/provider/__main__.py
```

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:10003 (Press CTRL+C to quit)
```

`Ctrl+C` to stop. Provider is complete, now both agents are ready. Now wire them together.

---

## Step 4 — Run end-to-end PSI

### 4.1 Create the PSI client

The PSI client is a one-shot script that lives alongside the Consumer and reuses its identity. It loads Consumer's private key, reads one customer row from the DB, and runs the PSI protocol against the Provider.

Create `my-a2a-agents/consumer/psi_client.py`:

```python
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

    from a2a.types import AgentCapabilities, AgentCard, AgentInterface

    card_url = os.getenv("CARD_URL", "http://localhost:10002")
    card = AgentCard(
        name="Consumer",
        description="Hello world + AP3 initiator",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=None),
    )
    card.supported_interfaces.append(AgentInterface(protocol_binding="JSONRPC", url=card_url))

    commitment = CommitmentMetadata(
        agent_id="consumer_customers",
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
            card_url=card_url,
            private_key=private_key,
            public_key=public_key,
            role="ap3_initiator",
            operation_type="PSI",
        ),
        operation=PSIOperation(),
    )

    result = await ap3.run_intent(
        peer_url=os.getenv("PROVIDER_URL", "http://localhost:10003"),
        inputs={"customer_data": fetch_default_customer(db_path)},
    )
    print("PSI result:", result.result_data.metadata["description"])

if __name__ == "__main__":
    asyncio.run(main())
```

### 4.2 Run all three terminals

From the **repo root** (the directory that contains `my-a2a-agents/`), open three terminals:

```bash
# Terminal 1 — Provider
uv run --package provider-agent python my-a2a-agents/provider/__main__.py
```

```bash
# Terminal 2 — Consumer
uv run --package consumer-agent python my-a2a-agents/consumer/__main__.py
```

```bash
# Terminal 3 — PSI client
uv run --package consumer-agent python my-a2a-agents/consumer/psi_client.py
```

Expected output:

```
PSI result: {"is_match":true}
```

The private computation works — `Joe Quimby` is in both databases, and the match was found without either side revealing their full list.

### 4.3 Try a non-match

Swap the customer for someone not on the sanctions list and rerun:

```bash
sqlite3 my-a2a-agents/consumer/data/initiator.db "DELETE FROM customer_entries WHERE id = 1;"
sqlite3 my-a2a-agents/consumer/data/initiator.db "INSERT INTO customer_entries(row) VALUES ('Alice Nobody,X0000000,1 Nowhere St');"
```

```bash
uv run --package consumer-agent python my-a2a-agents/consumer/psi_client.py
```

Expected output:

```
PSI result: {"is_match":false}
```

`Alice Nobody` is correctly identified as not present in the Provider's sanction list.

---

## Recap

Congratulations! You have just built two A2A agents and enabled them with AP3.

This involved:

- adding SQLite-backed datasets (customers and sanctions list)
- attaching the AP3 extension to AgentCards for capability discovery
- connecting AP3 middleware as a protocol handler
- running PSI end-to-end between Consumer and Provider

Check other ways to integrate AP3: [Codelab - AP3 Privacy Agent](./codelab-privacy-agent.md).

Happy computing!