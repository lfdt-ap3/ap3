<!-- markdownlint-disable MD041 -->
<h1><strong>FAQ</strong></h1>

## Where can I try AP3 without setting anything up?

Open the **[AP3 Playground](https://playground.ap3-protocol.org/)**. It runs a live PSI flow in the browser and surfaces the agent cards, on-wire envelopes, signed directives, audit timeline, and runtime logs — useful for getting a feel for the protocol before integrating the SDK.

## What problem does AP3 solve?

Two agents that don't fully trust each other need to compute a function over their respective private inputs and learn only the result. AP3 standardises the protocol surface — roles, commitments, directives, the on-wire envelope, and the privacy-preserving operations on top — so a [`Bank A` agent](use-cases/finance.md) and a `Bank B` agent can speak PSI to each other regardless of vendor.

## How is AP3 different from end-to-end encryption?

E2EE protects data *in transit between people who already trust each other with the contents*. AP3 lets two parties **compute together without ever revealing the contents** to each other. The receiver doesn't decrypt the initiator's input — it runs cryptographic rounds against it. Only a scoped output (a boolean, a count, an intersection) is revealed.

## What operations are shipped today?

[PSI](functions/psi.md). Other functions (set ops, private pricing, sanctions screening, geospatial matching, credential verification, multi-party aggregation, custom DSL) are under [private preview](functions/whats-coming.md).

## Do I need a TEE to run AP3?

No, not for the protocol itself. PSI runs on regular machines. A TEE becomes the **recommended deployment posture** for production service providers because it adds hardware-rooted assurance that the right code ran against the committed dataset — see [Security](security.md).

## What's the relationship between AP3 and AP2?

They compose: **AP3 produces a verifiable result, AP2 settles the fee**. AP3 owns the privacy-preserving compute lane (signed commitments, signed intents, signed results, replay protection); AP2 (and rails like x402, MPP) own pricing, quoting, and settlement. See the [Overview](index.md#ap2-and-ap3) for the framing and [Monetize Your Data](use-cases/monetize-with-service-provider.md) for the operator's view.

## Can I use AP3 without A2A?

The protocol is transport-agnostic — the on-wire envelope is just `Part.data`. Today's reference SDK uses [A2A](extension.md) as the messaging fabric because it's the cleanest way to carry signed payloads between independent agents. If you have your own messaging layer, the AP3 verb-and-directive layer drops on top.

## Is AP3 production-ready?

The released SDK ships PSI with signed commitments, signed intents, signed results, replay protection, and canonical signing for cross-language verification. Receiver-signed receipts, first-class TEE attestations, formal proofs of correctness, and standardised negotiation/settlement artifacts are tracked on the [Roadmap](roadmap.md).

## How do I add a new operation?

Operations are pluggable verbs on top of the protocol surface. The four-part contract (role layout, input schema, wire transcript, result shape) is in [Functions](operations.md#what-operation-gives-you-concretely). The [custom DSL](functions/whats-coming.md) — under private preview — will let domain teams define new operations without forking the protocol.

## Which languages does the SDK support?

Python today (Pydantic models, signed canonical JSON). Cross-language verification is a hard requirement — directives are designed to verify byte-for-byte against the same key in any language. Additional language SDKs are tracked on the [Roadmap](roadmap.md).
