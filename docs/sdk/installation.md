# Installation

The AP3 SDK is published on PyPI as two packages:

- **`ap3`** — the protocol surface: types, directives, signing, services, A2A middleware.
- **`ap3-functions`** — the cryptographic operation implementations (currently PSI). Imports as `ap3_functions`. Pulls in `ap3` automatically.

Most users want both. Install `ap3-functions` and you get `ap3` as a transitive dependency.

## Prerequisites

- **Python ≥ 3.11, < 3.14**

## Install with `uv` (recommended)

[`uv`](https://docs.astral.sh/uv/) is fast and handles virtual environments for you.

```bash
uv add ap3-functions
```

Or, if you only need the protocol surface (no PSI runtime):

```bash
uv add ap3
```

For A2A-based hosting/clients, install the optional extra:

```bash
uv add "ap3[a2a]"
```

If you don't have `uv` yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install with `pip`

```bash
pip install ap3-functions
```

Or just the protocol surface:

```bash
pip install ap3
```

With the A2A extra:

```bash
pip install "ap3[a2a]"
```

## Verify Installation

```python
import ap3
import ap3_functions

print(ap3.__version__)  
print(ap3_functions.__version__)
```

## Dependencies

Pulled in automatically:

- **`ap3`** — `pydantic`, `httpx`, `cryptography`, `protobuf`
- **`ap3[a2a]`** extra — `a2a-sdk[http-server]`, `grpcio`, `uvicorn`, `starlette`
- **`ap3-functions`** — depends on `ap3`; pure-Python PSI implementation built on `rbcl` (libsodium / Ristretto255) and `merlin_transcripts`

## Working from source

If you want to hack on the SDK itself, clone the repo and use the workspace:

```bash
git clone https://github.com/lfdt-ap3/ap3.git
cd ap3
uv sync
source .venv/bin/activate  # macOS / Linux
```

The SDK source lives under `src/ap3/`, and `ap3-functions` lives under `packages/ap3-functions/`:

```text
ap3/
├── src/ap3/
│   ├── types/          # Core types, directives, and error models
│   ├── core/           # Base Operation contract for protocol implementations
│   ├── signing/        # Ed25519 signing primitives for directives/commitments
│   ├── services/       # Commitment metadata + discovery + compatibility
│   └── a2a/            # A2A middleware (PrivacyAgent, AP3Middleware)
├── packages/
│   └── ap3-functions/  # Protocol implementations (e.g., PSI). Import as `ap3_functions`.
├── examples/           # Working examples
├── tests/              # Test suite
└── docs/               # This documentation
```

## Next Steps

1. [Configure your environment](configuration.md) — set up API keys
2. [Quickstart](../codelab-privacy-agent.md) — get started with an end-to-end codelab
3. [API Reference](api-reference.md) — explore the SDK surface

## Support

If you run into issues:

- Report bugs: [GitHub Issues](https://github.com/lfdt-ap3/ap3/issues)
- Contact: support@silencelaboratories.com
