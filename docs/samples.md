<!-- markdownlint-disable MD041 -->
<h1><strong>Samples</strong></h1>

Runnable examples of AP3 in the [main repository](https://github.com/lfdt-ap3/ap3/tree/main/examples). Each one ships with a README, a Docker compose file (where applicable), and an end-to-end test you can run locally.

## PSI walkthroughs

### `psi_simple` — minimal AP3 PSI over A2A

The smallest possible setup: one initiator with a customer record, one receiver with a SQLite-backed sanction list. PSI runs end-to-end and the initiator prints a signed `PrivacyResultDirective`. Local Python or `docker compose up`.

→ [`examples/psi_simple`](https://github.com/lfdt-ap3/ap3/tree/main/examples/psi_simple)

### `a2a-example` — two-company PSI with A2A middleware

Same use case as `psi_simple` but each side is a standard A2A server with AP3 layered as middleware (no separate privacy server). Companion to the [`A2A + AP3 middleware` codelab](codelab-a2a-ap3.md).

→ [`examples/a2a-example`](https://github.com/lfdt-ap3/ap3/tree/main/examples/a2a-example)

### `psi_adk_simple` — AP3 PSI inside Google ADK agents

Two ADK agents with embedded AP3 servers. `adk web` brings them both up; you trigger PSI via chat. Useful as a template for slotting AP3 into an ADK-based agent stack.

→ [`examples/psi_adk_simple`](https://github.com/lfdt-ap3/ap3/tree/main/examples/psi_adk_simple)

## Inspector / playground

### `ap3_playground` — glass-box developer demo

A "show me what's actually happening" demo: runs a PSI flow and renders an inspector UI of agent cards, on-wire envelopes, signed directives, the audit timeline, and runtime logs. Useful when debugging interop or onboarding to the protocol.

**Try it live:** [playground.ap3-protocol.org](https://playground.ap3-protocol.org/) — no setup required.

→ Source: [`examples/ap3_playground`](https://github.com/lfdt-ap3/ap3/tree/main/examples/ap3_playground)
