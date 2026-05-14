# ADK + AP3 PSI Example

Two Google ADK agents perform a privacy-preserving sanction check using Private Set Intersection (PSI). The initiator holds a customer record; the receiver holds a sanction list. AP3 runs the PSI such that neither side reveals its raw data.

- **psi_initiator** (port `10002`) — holds customer data, triggers PSI via chat
- **psi_receiver** (port `10003`) — holds a sanction list, responds to PSI requests

Both AP3 servers are embedded directly in the ADK agents. `adk web` is enough to bring them up.

---

## Prerequisites

- Python `>=3.11` and [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- A [Gemini API key](https://aistudio.google.com/apikey)
- This repo cloned and the root workspace synced:

```bash
cd <repo-root>
uv sync
```

---

## Environment setup

Copy the example env files for each agent and fill in your API key:

```bash
cd examples/psi_adk_simple

cp psi_initiator/.env.example psi_initiator/.env
cp psi_receiver/.env.example psi_receiver/.env
```

Open both `.env` files and set:

```
GOOGLE_API_KEY=<your-gemini-api-key>
```

All other values have sensible defaults for local development. See [Environment variables](#environment-variables) for the full reference.

---

## Install dependencies

```bash
cd examples/psi_adk_simple
uv sync
```

> `uv run` invokes commands inside the managed venv without a manual `source .venv/bin/activate`.

---

## Run

The receiver must be active before PSI runs. Open two terminals, **both `cd`'d into `examples/psi_adk_simple`**.

**Terminal 1 — receiver:**

```bash
cd examples/psi_adk_simple
uv run adk web
```

In the ADK UI at http://127.0.0.1:8000, select **`psi_receiver`**. The AP3 receiver server starts automatically when ADK loads the module — no message needed. You can send `hello` to confirm it's ready.

**Terminal 2 — initiator:**

```bash
cd examples/psi_adk_simple
uv run adk web --port 8081
```

In the ADK UI at http://127.0.0.1:8081, select **`psi_initiator`** and ask:

```
Check Joe Quimby,S4928374,213 Church St
```

or

```
Is Bob Johnson,C3456789,789 Pine Street sanctioned?
```

---

## Expected output

The initiator agent interprets the PSI result and replies in natural language. Example responses:

**Match (customer is in the sanction list):**

> The customer Joe Quimby (ID: S4928374) was found in the receiver's sanction list. Note that this check is privacy-preserving — the receiver never saw the customer's details, and the sanction list was never revealed to us.

**No match:**

> The customer was not found in the receiver's sanction list. The PSI protocol confirmed this without either side revealing their raw data.

Default seed data: `Joe Quimby,S4928374,213 Church St` is in the sanction list — PSI returns a match.

---

## Sanction list

The receiver loads its sanction list from `psi_receiver/data/sanctions.txt`. The file is auto-created with defaults on first run. Edit it and restart the receiver to pick up changes.

Default contents:

```
Joe Quimby,S4928374,213 Church St
C. Montgomery Burns,S9283746,1000 Mammon Lane
Bob Johnson,C3456789,789 Pine Street
```

---

## Multi-model support

Both agents support Gemini (default), Claude, and OpenAI via two env vars:

| `MODEL_PROVIDER` | Required key | Model name docs |
|---|---|---|
| `gemini` (default) | `GOOGLE_API_KEY` | [Google AI models](https://ai.google.dev/gemini-api/docs/models) |
| `claude` | `ANTHROPIC_API_KEY` | [Anthropic models](https://docs.anthropic.com/en/docs/about-claude/models) |
| `openai` | `OPENAI_API_KEY` | [OpenAI models](https://platform.openai.com/docs/models) |

Set `MODEL_NAME` to any model ID supported by your chosen provider. If omitted, a built-in fallback is used — check the provider docs for the latest recommended model.

Claude and OpenAI require LiteLLM support:

```bash
uv add 'google-adk[extensions]'
```

Example `.env` for Claude:

```
MODEL_PROVIDER=claude
MODEL_NAME=<model-id-from-anthropic-docs>
ANTHROPIC_API_KEY=<your-key>
```

---

## Environment variables

| Variable | Default | Used by | Description |
|---|---|---|---|
| `MODEL_PROVIDER` | `gemini` | both agents | LLM provider: `gemini`, `claude`, `openai` |
| `MODEL_NAME` | *(built-in fallback)* | both agents | Model ID for the chosen provider — see provider docs for latest |
| `GOOGLE_API_KEY` | — | gemini | Gemini API key |
| `ANTHROPIC_API_KEY` | — | claude | Anthropic API key |
| `OPENAI_API_KEY` | — | openai | OpenAI API key |
| `AP3_PORT` | `10002` / `10003` | both agents | Port for the AP3 A2A server |
| `CARD_URL` | `http://localhost:{AP3_PORT}` | both agents | Public URL peers use to fetch this agent's card |
| `HOST` | `127.0.0.1` | both agents | Bind address for the AP3 server |
| `PSI_RECEIVER_URL` | `http://localhost:10003` | initiator | Receiver's base URL |

---

## How it works

1. **Import → server starts.** The receiver calls `ensure_started()` at module import time, spawning a daemon thread that runs an `ap3.a2a.PrivacyAgent` A2A server.
2. **Keys are persisted.** Each agent generates an Ed25519 keypair on first run and saves it to `ap3_keys.json` (gitignored). Keys are reloaded on restart — agent identity stays stable.
3. **PSI flow.** When the user asks the initiator to check a customer, the LLM calls `run_psi_check`. The tool sends a signed `PrivacyIntentDirective` to the receiver, runs the PSI rounds, and returns a match verdict. The receiver never reveals the raw sanction list.

---

## Codelab (from scratch)

See [Privacy Agent codelab](../../docs/codelab-privacy-agent.md).

---

## Security notice

This example is for demonstration. In production:

- Do not store `ap3_keys.json` in source control. Restrict file permissions (`chmod 600`).
- Replace the flat-file sanction list with a production-grade data store.
- Treat any agent outside your control as potentially untrusted.
