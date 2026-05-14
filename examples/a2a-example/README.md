# AP3 A2A Example

Two companies perform a privacy-preserving sanction check using [Private Set Intersection (PSI)](https://en.wikipedia.org/wiki/Private_set_intersection). Neither party reveals its raw data — only whether an intersection (match) exists.

- **Company A** (initiator, port `10002`) — holds a customer list, triggers the PSI check
- **Company B** (receiver, port `10003`) — holds a sanction list, responds to PSI requests

Both agents are standard [A2A](https://github.com/google/a2a) servers with AP3 layered on as middleware. No separate privacy server is needed.

---

## Prerequisites

- Python `>=3.11` and [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Docker + Docker Compose (for the Docker path)

---

## Quick start — Docker

```bash
cd examples/a2a-example
make up
```

Both servers build and start. Company A is ready at `http://localhost:10002`, Company B at `http://localhost:10003`.

Run the PSI query (in a second terminal):

```bash
make psi-docker
```

Stop and clean up:

```bash
make down       # stop containers, keep volumes and keys
make clean      # stop containers, wipe volumes, delete local DBs and keys
```

Stream logs while running:

```bash
make logs
```

---

## Local development

Install dependencies for both agents:

```bash
cd examples/a2a-example
make setup
```

Start the servers and run PSI in one command:

```bash
make psi-local
```

Or manually in three terminals:

```bash
# Terminal 1 — start receiver first
cd examples/a2a-example/company_b && uv run .

# Terminal 2 — start initiator
cd examples/a2a-example/company_a && uv run .

# Terminal 3 — trigger PSI
cd examples/a2a-example/company_a && uv run psi_client.py
```

---

## Test the A2A endpoint

Verify that the standard A2A hello-world path still works alongside the PSI middleware:

```bash
# Company A
cd examples/a2a-example/company_a && uv run test_client.py

# Company B
cd examples/a2a-example/company_b && uv run test_client.py
```

---

## Build individual containers

From the **repo root**:

```bash
# Company B (start first — A depends on B)
docker build -f examples/a2a-example/company_b/Dockerfile -t ap3-company-b .
docker run -p 10003:10003 \
  -e HOST=0.0.0.0 -e PORT=10003 \
  -e CARD_URL=http://localhost:10003 \
  -v company-b-data:/app/examples/a2a-example/company_b/data \
  ap3-company-b

# Company A
docker build -f examples/a2a-example/company_a/Dockerfile -t ap3-company-a .
docker run -p 10002:10002 \
  -e HOST=0.0.0.0 -e PORT=10002 \
  -e CARD_URL=http://localhost:10002 \
  -e COMPANY_B_URL=http://host.docker.internal:10003 \
  -v company-a-data:/app/examples/a2a-example/company_a/data \
  ap3-company-a
```

> `HOST=0.0.0.0` is required in a container so the server binds to all interfaces.
> `COMPANY_B_URL` uses `host.docker.internal` to reach the B container when running standalone (not via Compose).

---

## Edit test data

Both DBs are auto-created and seeded on first run. All commands below run from `examples/a2a-example/`.

**Company A — customer list** (`company_a/data/initiator.db`):

```bash
# View
sqlite3 company_a/data/initiator.db "SELECT id, row FROM customer_entries ORDER BY id;"

# Add
sqlite3 company_a/data/initiator.db \
  "INSERT INTO customer_entries(row) VALUES ('Jane Doe,ID999,456 Oak Ave');"

# Remove
sqlite3 company_a/data/initiator.db "DELETE FROM customer_entries WHERE id = 2;"
```

**Company B — sanction list** (`company_b/data/receiver.db`):

```bash
# View
sqlite3 company_b/data/receiver.db "SELECT id, row FROM sanction_entries ORDER BY id;"

# Add
sqlite3 company_b/data/receiver.db \
  "INSERT INTO sanction_entries(row) VALUES ('Jane Doe,ID999,456 Oak Ave');"

# Remove
sqlite3 company_b/data/receiver.db "DELETE FROM sanction_entries WHERE id = 2;"
```

Default seed data:
- Company A has `Joe Quimby` (matches Company B's sanction list)
- Company B has `Joe Quimby`, `C. Montgomery Burns`, `Bob Johnson`

Expected PSI output: **match found**.

---

## Environment variables

All variables have sensible defaults for local development. No `.env` file needed unless you want to override them. For Docker, everything is already set in `docker-compose.yml`.

```bash
cp .env.example .env   # then edit as needed
```

| Variable | Default | Used by | Description |
|---|---|---|---|
| `HOST` | `127.0.0.1` | both servers | Bind address. Set to `0.0.0.0` to expose outside localhost. |
| `PORT` | `10002` / `10003` | both servers | Port the server listens on. |
| `CARD_URL` | `http://localhost:10002` / `10003` | both servers, `test_client.py` | Public URL where this agent's card is reachable by peers. |
| `COMPANY_B_URL` | `http://localhost:10003` | `psi_client.py` | Company B's base URL. |
| `COMPANY_A_PORT` | `10002` | `docker-compose.yml` | Override Company A's host-side port mapping without editing Compose. |
| `COMPANY_B_PORT` | `10003` | `docker-compose.yml` | Override Company B's host-side port mapping without editing Compose. |

---

## How it works

See [INTEGRATION.md](./INTEGRATION.md) for a step-by-step walkthrough of how AP3 was layered onto a standard A2A hello-world server.

---

## Security notice

This example is for demonstration purposes. When building production applications:

- Treat any agent outside your control as potentially untrusted.
- Do not store `ap3_keys.json` in source control. Restrict file permissions (`chmod 600`).
- SQLite is used here for simplicity. Replace with a production-grade store for real deployments.
