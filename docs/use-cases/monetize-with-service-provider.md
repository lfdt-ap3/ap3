---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Monetize Your Data</strong></h1>

Some of the most valuable datasets — sanctions lists, fraud signals, supplier quality benchmarks, blacklists, KYC corpora, vector indexes — are also the ones their owners can't share. Direct data sharing leaks competitive intelligence, breaks regulations like GDPR and CCPA, or undoes the very moat that made the dataset valuable in the first place.

A **service provider agent** turns that constraint into a product. Instead of selling rows, you sell **answers computed against your data**, with cryptographic guarantees that the data itself never leaves your boundary. This page is the operator's guide to standing one up on AP3.

## What is a service provider agent?

In AP3, an agent that takes the [`ap3_receiver`](../roles.md#ap3_receiver) role *is* a service provider:

> *"The receiver is more accurately a **service provider**: it holds the private dataset against which the initiator wants to run a computation, and it actively participates in every cryptographic round."* — [Roles](../roles.md#ap3_receiver)

In other words: another agent (the [`ap3_initiator`](../roles.md#ap3_initiator)) shows up with a private query. You run a privacy-preserving operation against your private dataset. The initiator gets a minimal answer (a boolean, a score, an intersection); you get paid for the computation. Neither side sees the other's inputs.

That's the entire shape of the business. The rest is operational.

## What you sell, what stays private

| What you sell | What never leaves your boundary |
|---|---|
| The *answer* of an operation (e.g. "is this candidate on my blacklist?") | The full blacklist |
| A *score* from a secure function evaluation against your model | The model weights |
| A *count* of matches in a private intersection | The matched entries themselves |
| A signed result *receipt* a counterparty can show its auditor | The query a counterparty asked |

The asymmetry is a property of the [operation](../operations.md), not of being a service provider. PSI, for instance, is built so that even when both sides run cryptographic rounds, **only the initiator learns the intersection** — by design, your dataset stays unrevealed to the counterparty.

> See [Use Cases](index.md) for concrete patterns: PSI for sanctions/blacklist screening, Secure Function Evaluation for joint risk scoring, Secure Dot Product for product/quality matching.

## The end-to-end flow, in business terms

This is what an AP3 service-provider engagement looks like across the [AP3 Lifecycle](../lifecycle.md). Each step ties to a concept page if you want to dig in.

1. **Publish what you'll compute against.** Sign and serve a [commitment](../commitments.md) — the public claim *"I have a dataset of this shape, this size, this freshness, and I am willing to compute against it."* The commitment travels inside your [AgentCard](../extension.md).
2. **Be discoverable.** Counterparty agents fetch your AgentCard, evaluate compatibility (operation match, role complement, commitment shape), and decide whether to engage — all *before* any private input crosses the wire.
3. **Accept a signed intent.** The initiator sends a [`PrivacyIntentDirective`](../directives.md): operation, participants, expiry, replay nonce, signed under their key. You verify everything *before* touching the cryptographic payload.
4. **Run the operation.** Process the protocol rounds (e.g. PSI's `msg1` → `msg2`) inside your runtime. The cryptography enforces minimum disclosure.
5. **Return a result.** A signed [`PrivacyResultDirective`](../directives.md) carrying the encoded result, an integrity hash, and metadata. The initiator verifies the signature against the key advertised in your AgentCard.
6. **Get paid.** AP3 owns the privacy-preserving compute lane; **AP2 owns settlement**. As [the Overview](../index.md#ap2-and-ap3) puts it: *"AP3 produces a verifiable result, AP2 settles the fee that the receiving agent charges for participating."* Pricing, quoting, and settlement rails (AP2 / x402 / MPP) are the commercial layer on top of the verified result.

!!! note "Where AP3 stops and where commerce begins"
    AP3 today gives you the **privacy + integrity** half: signed commitments, signed intents, signed results, replay protection, canonical signing for cross-language verification. Standardized **negotiation artifacts** (signed quotes, fees, limits) and **settlement** are tracked under [Stage 4 and Stage 8 of the Agentic Stack](../agentic-stack.md#stage-4-negotiate-how-will-we-collaborate) and on the [Roadmap](../roadmap.md). Today most teams paper over this with off-protocol contracts and explicit AP2 calls; first-class signed-terms artifacts come later.

## Pricing and settlement

AP3 stays out of the pricing lane on purpose. The protocol gives you the raw materials:

- A **commitment** lets you advertise *what* you compute against (think: SKU).
- A **directive** lets a counterparty open a session against a specific commitment and operation (think: order line).
- A **signed result** lets the counterparty's agent prove to its own systems that the work it's about to pay for actually happened.

[AP2](https://ap2-protocol.org/) is the standards-track way to settle the fee. The simplest pattern, paraphrased from the [Overview](../index.md#ap2-and-ap3): *AP3 produces a verifiable result; AP2 binds that result into a payment.* Quoting (prepaid vs postpaid), settlement rails, refund and dispute policy are negotiated on top.

A typical commercial flow:

1. **Quote.** Counterparty fetches your AgentCard, sees your commitments and supported operations, and asks for terms (operation, expected volume, optional SLA).
2. **Order.** Counterparty's agent issues a [`PrivacyIntentDirective`](../directives.md) referencing the agreed operation and (eventually) a signed terms blob.
3. **Execute.** Your service provider runs the operation in a TEE, returns a signed `PrivacyResultDirective`.
4. **Settle.** AP2 binds the signed result + agreed terms into a payment instruction. The fee clears against the verifiable artifact, not a vague "we did some compute" claim.

## Today vs. on the roadmap

| Capability | Today | Roadmap |
|---|---|---|
| Privacy of inputs (PSI) | Cryptographically enforced by the operation | — |
| Signed directives (intent / result) | Yes — Ed25519 with canonical JSON, domain-separated | — |
| Signed commitments | Yes | Membership commitments, dataset proofs |
| Replay protection / canonical signing | Yes | — |
| **Real proof of computation** | Placeholder fields only (`attestation="experimental_placeholders"`) | TEE attestation, ZK proofs, receiver-signed receipts |
| Key rotation / revocation | Operational only | Protocol semantics in discovery + verification |
| Standard negotiation artifacts (signed terms, fees) | Off-protocol | First-class artifacts |
| Settlement | Out of scope (use AP2) | Tighter binding to verified results |

The honest summary: **the wire format and message contract are stable; cryptographic proof of correct execution is the active work.** A service provider that deploys inside a TEE today is buying the upgrade path — when the proof slot turns real, your existing deployment fills it without re-architecting.

## See also

- [Roles](../roles.md) — formal definition of `ap3_receiver` / service-provider responsibilities.
- [Commitments](../commitments.md) — what you publish about your dataset, and the limits of self-asserted commitments today.
- [AP3 Lifecycle](../lifecycle.md) — the Negotiate / Execute / Verify / Settle stages in detail.
- [Private APIs](../operations.md) — the four trust strategies (open-source, multi-sig, TEE, formal verification) and the recommended-posture table.
- [Agentic Stack](../agentic-stack.md) — engineering view of where AP3 fits among identity, negotiation, and settlement.
- [Use Cases](index.md) — concrete shapes (sanctions, fraud, supply chain, hiring, FMCG, delivery) where the service-provider model already pays.
- [Codelab: A2A + AP3 middleware](../codelab-a2a-ap3.md) — drop AP3 into an existing A2A server without forking it.
