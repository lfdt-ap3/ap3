---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Codelab: Sanctions check (Simple)</strong></h1>

**Estimated time:** 15 min

This codelab shows how to create agents and perform Private Set Intersection (PSI) between them.

This integration is using a simple and clean `PrivacyAgent` method. 



!!! info
    If you need a more advanced integration with greater flexibility, take a look at the lower-level integration method in the [**A2A + AP3 middleware**.](https://ap3-protocol.org/codelab-a2a-ap3/)

Here is the use case we implement here:

- **Consumer (consumer)** has a customer list to check for sanctioned individuals. It runs a `PrivacyAgent` and initiates PSI
- **Provider (provider) has a sanction list** and provides privacy preserving lookups as a service. It runs own instance of `PrivacyAgent` and answers to PSI requests

---

## What is `PrivacyAgent`?

`PrivacyAgent` is a **ready-to-run A2A server** with AP3 out of the box.

It handles most of the work under the hood for you:

- **Serves an AgentCard** with AP3 extension and fields
- **Signs and verifies AP3 directives**
- **Runs a privacy-preserving function** (`PSIOperation` in this example)

---

## What you’ll build

As the result, you’ll have up and running:

- **Consumer agent server** at `http://localhost:10002`
- **Provider agent server** at `http://localhost:10003`
- Two SQLite Databases:
    - Customer list
    - Sanction list

A completed PSI (Private Set Intersection) operation returns **match found / no match** as the outcome.

---

## Prerequisites

- Python **3.11–3.13**
- [`uv`](https://docs.astral.sh/uv/)

---

## Step 1: Create the project layout

From the repo root:

```bash
mkdir -p my-privacy-agents/consumer my-privacy-agents/provider
```

You’ll end up with:

```
my-privacy-agents/
  consumer/
  provider/
```

### 1.1 Root `pyproject.toml` (uv workspace)

Add a **workspace** manifest at the **repo root** (next to `my-privacy-agents/`):

```toml
[project]
name = "my-privacy-agents"
version = "0.1.0"
requires-python = ">=3.11,<3.14"

[tool.uv.workspace]
members = [
  "my-privacy-agents/consumer",
  "my-privacy-agents/provider",
]
```

---

## Step 2: Add `pyproject.toml` for both agents

Create `my-privacy-agents/consumer/pyproject.toml`:

```toml
[project]
name = "ap3-privacy-consumer"
version = "0.1.0"
description = "AP3 PrivacyAgent PSI consumer"
requires-python = ">=3.11,<3.14"
dependencies = [
  "a2a-sdk[http-server]>=1.0.2",
  "ap3-functions>=1.2.1",
  "ap3[a2a]>=1.2.1",
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

Create `my-privacy-agents/provider/pyproject.toml`

```toml
[project]
name = "ap3-privacy-provider"
version = "0.1.0"
description = "AP3 PrivacyAgent PSI provider"
requires-python = ">=3.11,<3.14"
dependencies = [
  "a2a-sdk[http-server]>=1.0.2",
  "ap3-functions>=1.2.1",
  "ap3[a2a]>=1.2.1",
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

---

## Step 3: Add SQLite DB helpers

### 3.1 Provider DB (`provider/db.py`)

Create `my-privacy-agents/provider/db.py`:

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

### 3.2 consumer DB (`consumer/db.py`)

Create `my-privacy-agents/consumer/db.py`:

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

---

## Step 4: Create the Provider `PrivacyAgent`

We’ll go step by step to create the agent. See 5.6 if you need the complete resulting `__main__.py` .

### 4.1 Load provider data from SQLite

Add the imports at the top of `my-privacy-agents/provider/__main__.py`:

```python
from pathlib import Path
from db import fetch_sanction_list
```

…and seed/load the DB at the start of `main()`:

```python
def main() -> None:
    fetch_sanction_list(Path(__file__).parent / "data" / "provider.db")
    ...
```

On the first run the helper will:

- create `my-privacy-agents/provider/data/provider.db`
- create a `sanction_entries` table
- seeds three default row for the demo


### 4.2 Generate an AP3 identity keypair

AP3 directives are signed. The provider needs a keypair so it can:

- publish its **public key** in the AgentCard
- verify signatures from peers

!!!info
    You should persist these keys in actual deployments. For simplicity, this codelab generates a new keypair each run.

```python
private_key, public_key = generate_keypair()
```

### 4.3 Define a Commitment

The provider advertises a [**commitment**](https://ap3-protocol.org/commitments/) describing its data:

- data structure: `BLACKLIST`
- format: structured
- entry/field counts (metadata only)

```python
commitment = CommitmentMetadata(
        agent_id="company_b_sanctions",
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
```

### 4.4 Construct the `PrivacyAgent`

Key fields:

- `card_url`: where peers fetch your AgentCard (must match the reachable URL)
- `role="ap3_receiver"`: this agent answers PSI requests
- `operation=PSIOperation()`: the AP3 PSI implementation
- `receiver_config_provider`: provides receiver-only configuration (the sanction list)

```python
agent = PrivacyAgent(
        name="PSI provider",
        description="Holds a sanction list; performs PSI on request",
        card_url=f"http://localhost:{port}",
        host="localhost",
        port=port,
        role="ap3_receiver",
        operation=PSIOperation(),
        commitment=commitment,
        private_key=private_key,
        public_key=public_key,
        receiver_config_provider=lambda: {"sanction_list": sanction_list},
        # Dev-only: consumer advertises a loopback card URL. Remove in production —
        # the SSRF guard will otherwise refuse the consumer's localhost initiator URL.
        allow_private_initiator_urls=True,
    )
```

### 4.5 Serve and wait for PSI requests

`async with agent.serving():` starts the HTTP server and serves the AgentCard + JSON-RPC.
`await agent.wait()` keeps the process alive.

### 4.6 Final file:

Here is the resulting `my-privacy-agents/provider/__main__.py`:

```python
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from ap3.a2a import PrivacyAgent
from ap3.signing.primitives import generate_keypair
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
from ap3_functions import PSIOperation

from db import fetch_sanction_list

async def main(port: int) -> None:
    sanction_list = fetch_sanction_list(Path(__file__).parent / "data" / "provider.db")
    private_key, public_key = generate_keypair()

    commitment = CommitmentMetadata(
        agent_id="company_b_sanctions",
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

    agent = PrivacyAgent(
        name="PSI provider",
        description="Holds a sanction list; performs PSI on request",
        card_url=f"http://localhost:{port}",
        host="localhost",
        port=port,
        role="ap3_receiver",
        operation=PSIOperation(),
        commitment=commitment,
        private_key=private_key,
        public_key=public_key,
        receiver_config_provider=lambda: {"sanction_list": sanction_list},
        # Dev-only: consumer advertises a loopback card URL. Remove in production.
        allow_private_initiator_urls=True,
    )

    async with agent.serving():
        print(f"[provider] serving on http://localhost:{port}")
        print(f"[provider] sanction list entries: {len(sanction_list)}")
        await agent.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=10003)
    args = parser.parse_args()
    asyncio.run(main(args.port))
```

---

## Step 5: Create the consumer `PrivacyAgent` (Consumer)

In AP3 PSI, the **consumer**:

- holds the private query (here: the “customer row”)
- publishes its AgentCard + public key so the provider can verify signatures
- starts a PSI run via `run_intent(...)`

See 5.6 if you need the complete resulting `__main__.py` .

### 5.1 Load consumer data from SQLite

Add the imports at the top of `my-privacy-agents/consumer/__main__.py`:

```python
from pathlib import Path
from db import fetch_customer_list
```

…and seed/load the DB at the start of `main()`:

```python
def main() -> None:
    fetch_customer_list(Path(__file__).parent / "data" / "consumer.db")
    ...
```

On the first run the helper will:

- create `my-privacy-agents/consumer/data/consumer.db`
- create a `customer_entries` table
- seeds a default row for the demo

We’ll use the **first row** as the input to PSI.

### 5.2 Generate an AP3 identity keypair

Same reasoning as the provider: the consumer needs keys to sign directives and to
publish its AP3 public key in its AgentCard.

```python
private_key, public_key = generate_keypair()
```

### 5.3 Define a Commitment

The consumer advertises a `CUSTOMER_LIST` commitment describing its dataset shape
and counts. This is metadata only: it does not reveal actual customer rows.

```python
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
```

### 5.4 Construct the consumer `PrivacyAgent`

Key fields:

- `role="ap3_initiator"`
- `operation=PSIOperation()`
- `card_url/host/port` so peers can fetch the card during the run

```python
agent = PrivacyAgent(
        name="PSI consumer",
        description="Checks customers against partner sanction lists",
        card_url=f"http://localhost:{port}",
        host="localhost",
        port=port,
        role="ap3_initiator",
        operation=PSIOperation(),
        commitment=commitment,
        private_key=private_key,
        public_key=public_key,
    )
```

### 5.5 Run PSI with `run_intent(...)`

Once the consumer is serving, it can:

- fetch the provider’s AgentCard (to verify AP3 public key)
- run the full PSI round-trip
- return a `PrivacyResultDirective` that includes the result metadata (match / no match)
- exits after completion

```python
result = await agent.run_intent(
            peer_url=provider_url,
            inputs={"customer_data": customer},
        )
```

### 5.6 Final file: `__main__.py`

Here is the resulting `my-privacy-agents/consumer/__main__.py`:

```python
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from ap3.a2a import PrivacyAgent
from ap3.signing.primitives import generate_keypair
from ap3.types import CommitmentMetadata, DataFormat, DataFreshness, DataStructure, Industry
from ap3_functions import PSIOperation

from db import fetch_customer_list, fetch_default_customer

async def main(port: int, provider_url: str) -> None:
    db_path = Path(__file__).parent / "data" / "consumer.db"
    customer_list = fetch_customer_list(db_path)
    private_key, public_key = generate_keypair()

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

    agent = PrivacyAgent(
        name="PSI consumer",
        description="Checks customers against partner sanction lists",
        card_url=f"http://localhost:{port}",
        host="localhost",
        port=port,
        role="ap3_initiator",
        operation=PSIOperation(),
        commitment=commitment,
        private_key=private_key,
        public_key=public_key,
    )

    async with agent.serving():
        customer = fetch_default_customer(db_path)
        print(f"[consumer] serving on http://localhost:{port}")
        print(f"[consumer] checking '{customer}' against {provider_url}")

        result = await agent.run_intent(
            peer_url=provider_url,
            inputs={"customer_data": customer},
        )

        print()
        print("=" * 72)
        print("PSI result:", result.result_data.metadata["description"])
        print("=" * 72)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=10002)
    parser.add_argument("--provider", default="http://localhost:10003")
    args = parser.parse_args()
    asyncio.run(main(args.port, args.provider))
```

---

## Step 6: Run it end-to-end

From the **repo root** (one level above `my-privacy-agents/`), in two separate terminals:

```bash
# Terminal 1 (provider)
uv lock
uv sync --package ap3-privacy-provider
uv run --package ap3-privacy-provider python my-privacy-agents/provider/__main__.py
```

```bash
# Terminal 2 (consumer)
uv lock
uv sync --package ap3-privacy-consumer
uv run --package ap3-privacy-consumer python my-privacy-agents/consumer/__main__.py
```

Expected outcome: 

```python
PSI result: {"is_match":true}
```

If you see this in the client output, congratulations! The private computation works.

---

## Step 7: Try the non-match

From repo root:

```bash
# Replace Consumer customer with a non-matching row
sqlite3 my-privacy-agents/consumer/data/consumer.db "DELETE FROM customer_entries;"
sqlite3 my-privacy-agents/consumer/data/consumer.db \
  "INSERT INTO customer_entries(row) VALUES ('Alice Nobody,X0000000,1 Nowhere St');"
```

Rerun the consumer command. 

You should see:

```python
PSI result: {"is_match":false}
```

Correctly indicating that  `Alice Nobody...` is not in Provider’s sanction list.

---

## Recap

Congratulations! You have just built a minimal AP3 PSI system using `PrivacyAgent`.

It includes:

- provider that hosts an AP3-capable A2A server and loads its sanction list from SQLite
- consumer that hosts an AP3-capable A2A server, loads customer data from SQLite, and runs the private function

If you want to integrate AP3 into an *existing* A2A agent without replacing your server, see the [A2A + AP3 middleware](https://ap3-protocol.org/codelab-a2a-ap3/) codelab.

Happy computing!
