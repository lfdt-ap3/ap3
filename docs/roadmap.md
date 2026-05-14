---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Roadmap</strong></h1>

AP3 development roadmap is organized into three phases:

- **Phase 1** establishes the specification and reference implementation.
- **Phase 2** broadens framework, protocol, and identity coverage.
- **Phase 3** enables extensibility and outlines our vision for potential future research for the community.

### How to read the roadmap

Items below are **forward-looking**. Anything that's already in the SDK is referenced from the relevant Core Concepts page (e.g. PSI is in [Operations](operations.md), commitment signing is in [Commitments](commitments.md)). Anything *not* yet in the SDK — proof-of-computation, receiver-signed receipts, additional operations, custom commitments registry, etc. — is captured here.

Two specific items frequently come up in early conversations and are explicitly tracked in Phase 2 and 3:

* **Proof of computation** — the cryptographic guarantee that an agent actually computed honestly over the dataset it committed to. Until this lands, signed [Commitments](commitments.md) are tamper-evident *claims*, not proofs of dataset possession.
* **Custom commitments / DSL for private functions** — a path for declaring domain-specific data shapes and operations beyond the built-in enums. Today you can encode most of this via `DataSchema.metadata`; first-class support is in Phase 3.

### Phase 1 — Foundation (first two months)

- **AP3 protocol specification v1.0:** versioned specification published as an extension to Agent2Agent (A2A), with explicit extension points identified for ACP, AGP/SLIM, and ANP. Covers message formats, capability-disclosure semantics, mandate and attestation structures, and the SMPC and TEE trust-model definitions.
- **Reference SDK:** open-source SDK in Python and TypeScript. Build tools for Google ADK, CrewAI, LangGraph, and AutoGen via thin integration adapters.
- **Private compute API:** private Set Intersection (PSI) API to be exposed, as the most demanded privacy preserving computation function.
- **Documentation:** Published documentation and step-by-step tutorial on how to build your own agents from scratch and perform private compute. Deployed at [https://ap3-protocol.org](https://ap3-protocol.org/).
- **Code examples:** demo agents with architecture, reference implementation and mock data
- **Whitepaper:** complete white paper on cryptographic architecture, formal treatment of AP3's trust model, adversary assumptions, and privacy guarantees.

### Phase 2 — Breadth (months two to four)

- **Private compute API:** More APIs will be added in the next phases to provide custom logic building blocks for cross-organizational agent compute workflows: set operations (intersection, union, cardinality), threshold and qualification checks, private pricing and negotiation, compliance and sanctions screening, geospatial matching, credential verification, and multi-party aggregation.
- **Inter-agent protocol coverage:** support for ACP, AGP/SLIM, and ANP, to establish a more generic privacy layer across the agent ecosystem.
- **Capabilities and Reputation:** establishing cryptographic proofs for capability and joint reputation checks before negotiation.
- **Payments interoperability for Private Commerce:** a payment-protocol-agnostic binding layer for agentic commerce standards including AP2, x402, and the MPP family, enabling privacy-preserving commerce negotiation, followed by payment, workflows that compose AP3 confidentiality with existing mandate semantics.
- **Use case corpus:** integration cookbooks and reference deployments for cross-organizational scenarios including financial risk profiling, cross-border compliance, federated credential verification, and supply-chain reconciliation.

### Phase 3 — Extensibility and next research (months four onward)

- **Domain-Specific Language (DSL) for user-defined private functions:** tooling for programming domain-specific logic as privacy-preserving functions within the AP3 framework, in addition to standard APIs.
- **Guardrails and Policies:** a track for expansion of Policy Engine, compute guardrails and deterministic verification anchors.
- **Advanced protocol integration:** an open research track exploring integration of advanced MPC and threshold-cryptography constructions as they mature in the academic literature.
- **Formal verification:** a track for evaluation of AP3's core protocol flows against its stated security properties, in collaboration with academic contributors.
