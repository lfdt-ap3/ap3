<div align="center">

# Agent Privacy-Preserving Protocol - AP3

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/ap3.svg)](https://pypi.org/project/ap3/)
[![Docs](https://img.shields.io/badge/docs-ap3--protocol.org-informational)](https://ap3-protocol.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

[**Documentation**](https://ap3-protocol.org) · [**Examples**](#examples) · [**Contributing**](#contributing) · [**Discussions**](https://github.com/lfdt-ap3/ap3/discussions)

</div>

---

## Agent Privacy Preserving Protocol (AP3)

**Agent Privacy-Preserving Protocol (AP3)** is an open protocol that enables **distributed collective intelligence,** without sacrificing confidentiality and regulatory posture. Collective intelligence here means the capacity of autonomous agents, tools, humans, and institutions to reason jointly and accumulate shared context across organizational, jurisdictional, and vendor boundaries.

> 💡 **Documentation:** [https://ap3-protocol.org](https://ap3-protocol.org/)

Individually capable agents are already here; what the ecosystem lacks is a substrate on which they can _**think and act together**_ in a privacy preserving way. AP3 provides that layer to the existing stack. It is delivered as an extension to the open [Agent2Agent (A2A) protocol](https://a2a-protocol.org/latest/) in communication, integrates with [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) at the build stage and will expand support to other agentic frameworks.

> AP3 is being designed to support most common inter-agent communication protocols including the Agent Communication Protocol (ACP, originated by IBM, hosted at the Linux Foundation under the Agentic AI Foundation), the Agent Gateway Protocol (AGP / SLIM, originated by Cisco, hosted at the Linux Foundation under AGNTCY), and emerging decentralized protocols such as the Agent Network Protocol (ANP, originated by the open-source ANP community).

Its cryptographic core - Secure Multi-Party Computation (SMPC) for privacy preserving compute, supplemented by Trusted Execution Environment (TEE) attestation for execution integrity, would turn cross-boundary collaboration into a verifiable, policy-bound computation rather than an implicit trust assumption. Collective agentic and human context thereby becomes a cryptographically guaranteed intelligence layer.

AP3 aims to address a core question in multi-agent systems (MAS):

> Once multi-agent workflows span more than one trust domain, the engineering problem is no longer interoperability but governed execution: how do agents jointly compute, reason and collectively innovate over _**sensitive inputs,**_ [_**context graphs,**_](https://foundationcapital.com/ideas/context-graphs-ais-trillion-dollar-opportunity) and [_**memory**_](https://blog.cloudflare.com/introducing-agent-memory/). In doing so each participant's data remains confidential, every contribution to the output is cryptographically attributable, and the computation is verifiable without a single trusted intermediary.

## Examples

| Example | Framework | Description |
|---|---|---|
| [`psi_simple`](examples/psi_simple/) | Plain Python | Minimal two-process PSI sanctions check (initiator + receiver). |
| [`psi_adk_simple`](examples/psi_adk_simple/) | Google ADK | Two ADK agents running PSI through chat with embedded AP3 servers. |
| [`a2a-example`](examples/a2a-example/) | A2A | PSI layered onto standard A2A hello-world servers as middleware. |
| [`ap3_playground`](examples/ap3_playground/) | Web UI | Glass-box inspector: agent cards, envelopes, directives, audit timeline, tamper/replay scenarios. |

Each example has its own README with setup, Docker, and run instructions.

## Documentation

Full documentation lives at **[ap3-protocol.org](https://ap3-protocol.org)**. 

Highlights:

- [Installation Guide](docs/sdk/installation.md)
- [Configuration](docs/sdk/configuration.md)
- [API Reference](docs/sdk/api-reference.md)
- [Architecture](docs/architecture.md) · [Lifecycle](docs/lifecycle.md) · [Roles](docs/roles.md)
- [Directives](docs/directives.md) · [Commitments](docs/commitments.md) · [Operations](docs/operations.md)
- [Security model](docs/security.md) · [FAQ](docs/faq.md)
- [Troubleshooting](docs/sdk/troubleshooting.md)
- [Roadmap](docs/roadmap.md)

To preview the docs locally:

```bash
uv sync
uv pip install -r requirements.txt
uv run mkdocs serve
```

Build the static site into `site/`:

```bash
uv run mkdocs build --clean
```

## Project structure

```
ap3/
├── src/ap3/              # Core SDK: types, signing, services, A2A middleware
├── packages/
│   └── ap3-functions/    # Privacy operations (PSI, future MPC/HE primitives)
├── examples/             # Runnable examples (Python, A2A, ADK, web playground)
├── docs/                 # MkDocs site sources (architecture, SDK, codelabs)
├── tests/                # Unit + integration tests
└── .github/              # CI workflows, issue & PR templates
```

## Contributing

Contributions of all kinds are welcome — bug reports, fixes, new examples, docs, and new privacy operations.

1. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup, linting, testing, and PR guidelines.
2. Skim [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — we follow the Contributor Covenant.
3. For non-trivial changes, open an issue or [discussion](https://github.com/lfdt-ap3/ap3/discussions) first so we can align on direction.

When you file an issue or open a PR, GitHub will load the matching template:

| Action | Template |
|---|---|
| Report a bug | [`.github/ISSUE_TEMPLATE/bug_report.yml`](.github/ISSUE_TEMPLATE/bug_report.yml) |
| Request a feature | [`.github/ISSUE_TEMPLATE/feature_request.yml`](.github/ISSUE_TEMPLATE/feature_request.yml) |
| Open a pull request | [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) |

A quick pre-flight checklist before pushing:

- [ ] `uv run ruff check .` and `uv run ruff format .` are clean
- [ ] `uv run pytest -v` passes
- [ ] Tests added or updated for behavior changes
- [ ] No secrets, signing keys, or local state in the diff

## Community & support

- 💬 **Questions / how-do-I** — [GitHub Discussions](https://github.com/lfdt-ap3/ap3/discussions)
- 🐛 **Bugs & actionable feature requests** — [GitHub Issues](https://github.com/lfdt-ap3/ap3/issues)
- 📚 **Docs** — [ap3-protocol.org](https://ap3-protocol.org)
- 📨 **Support** — see [`SUPPORT.md`](SUPPORT.md)

## Security

Please **do not** open public issues for security vulnerabilities. Use GitHub's [Private Vulnerability Reporting](https://github.com/lfdt-ap3/ap3/security/advisories/new) instead. Full disclosure process is documented in [`SECURITY.md`](SECURITY.md).

## License

Licensed under the **Apache License, Version 2.0** — see [`LICENSE`](LICENSE).

## About

`Agent Privacy-Preserving Protocol - AP3` is an open source project under LF Decentralized Trust lab, contributed by [Silence Laboratories](https://silencelaboratories.com/). It is licensed under the Apache License 2.0 and is open to contributions from the community.