## AP3-enable the A2A Hello World sample (step-by-step)

This folder contains two copies of the upstream A2A “hello world” server:

- `company_a/`: AP3 **initiator** (runs PSI)
- `company_b/`: AP3 **receiver** (holds the sanction list)

The goal is to demonstrate **Case 2 / Option A**: *add AP3 as middleware to an
existing A2A agent server* (no separate `PrivacyAgent` server).

---

> **Running the example?** See [README.md](./README.md) for Docker and local setup instructions.

---

### Step 0 — Baseline

Each company starts as a normal A2A server:

- builds a public `AgentCard` and an extended card
- runs `HelloWorldAgentExecutor` to answer text requests
- uses `Starlette` with `create_agent_card_routes` + `create_jsonrpc_routes` to host JSON-RPC + agent-card routes

Files:

- `company_*/__main__.py`
- `company_*/agent_executor.py`

---

### Step 1 — Add AP3 identity (keys)

AP3 directives are signed, so each agent needs an Ed25519 keypair.

Change:

- Added `ap3_keys.json` persistence (created on first run) in:
  - `company_a/__main__.py`
  - `company_b/__main__.py`

Why:

- Company B must fetch Company A’s card and verify the intent signature.
- Persisting keys prevents identity drift across restarts.

---

### Step 2 — Attach the AP3 extension to the existing AgentCard

Change:

- Call `attach_ap3_extension(...)` on **both** the public card and the extended card.

Initiator (Company A):

- role: `ap3_initiator`
- operation: `PSI`
- commitment: `CUSTOMER_LIST`

Receiver (Company B):

- role: `ap3_receiver`
- operation: `PSI`
- commitment: `BLACKLIST`

Files:

- `company_a/__main__.py`
- `company_b/__main__.py`

---

### Step 3 — Create an AP3 protocol handler (middleware)

Change:

- Instantiate `AP3Middleware(...)` with an `AP3Identity(...)` and an operation implementation:
  - `PSIOperation()` from `ap3_functions`

Receiver config:

- Company B provides a `receiver_config_provider` with a `sanction_list`.
- In this example, the list is loaded from SQLite (`company_b/data/receiver.db`) to better
  mirror production systems (where data is not hardcoded in code).

Files:

- `company_a/__main__.py`
- `company_b/__main__.py`

---

### Step 4 — Wrap the existing executor (one server, two lanes)

Change:

- Replace the hello-world executor with:

  `PrivacyAgentExecutor(protocol_handler=ap3, llm_executor=HelloWorldAgentExecutor())`

Effect:

- AP3 protocol envelopes in `Part.data` are handled by AP3.
- Normal text messages still go to the hello-world executor.

Files:

- `company_a/__main__.py`
- `company_b/__main__.py`

---

### Step 5 — Initiate PSI (from the initiator)

Change:

- Added `company_a/psi_client.py` which calls `AP3Middleware.run_intent(...)` against Company B.
- The PSI input row is loaded from SQLite (`company_a/data/initiator.db`), instead of being hardcoded.
- URLs (`COMPANY_B_URL`, `CARD_URL`) are read from environment variables, defaulting to `localhost`.

See [README.md](./README.md) for run instructions (Docker and local).

---

### Step 6 — Keep the original hello-world clients working

Change:

- `company_*/test_client.py` reads the target URL from the `CARD_URL` environment variable,
  falling back to `http://localhost:10002` (Company A) and `http://localhost:10003` (Company B).
- No hardcoded URLs — override at runtime via `CARD_URL=http://...` when running against
  a non-default host or port.

