## AP3 Playground (Inspector + Playground)

This example is a **glass-box** developer demo for AP3: it runs a PSI flow and
renders an “under the hood” inspector (agent cards, envelopes, directives,
audit timeline, logs).

### Run

From repo root:

```bash
uv run --package ap3-playground ap3-playground
```

Then open `http://localhost:8088`.

### Docker

Build from repo root (Dockerfile lives under `examples/ap3_playground/`):

```bash
docker build -f examples/ap3_playground/Dockerfile -t ap3-playground .
docker run --rm -p 8088:8088 ap3-playground
```

Then open `http://localhost:8088`.

### Scenarios

- **Run PSI**: normal happy-path PSI round-trip.
- **Compatibility mismatch**: receiver refuses due to an incompatible peer.
- **Tamper: session id**: modifies `envelope.session_id` to demonstrate refusal.
- **Tamper: participants**: intent participants don’t include the receiver.
- **Replay**: resends the same first-round intent+msg1 to trigger replay protection.

