---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Roles</strong></h1>

In AP3, a **role** is a label an agent advertises in its `AgentCard` to tell the world what side of a privacy-preserving operation it can play. Roles are how an initiator and a counterparty *find* each other before any computation happens.

Roles answer one practical question: **"if we run an AP3 operation, who is going to do which part?"**

## Why roles exist

A privacy-preserving operation is rarely symmetric. In Private Set Intersection (PSI), for example:

* one side **starts the conversation** and is the only side that learns the intersection;
* the other side **provides its own private set** and crucially does *not* learn the initiator's query.

These are different jobs, with different inputs, different outputs, and different responsibilities. Putting them behind named roles lets:

* an initiator filter discovery results to "agents that can act as a receiver for the operation I want";
* each side load only the code path it needs;
* compatibility checks happen *before* a session starts, instead of failing mid-flight.

## The roles AP3 ships today

AP3 currently defines two roles, both centered on the PSI operation. As more [operations](operations.md) land, additional roles will be added — roles are operation-specific, not a global hierarchy.

### `ap3_initiator`

The agent that **starts** an AP3 operation. In PSI, the initiator is the side that:

* defines the computation parameters and constraints (which operation, which participants, expiry);
* creates and signs a [`PrivacyIntentDirective`](directives.md) for **every** outbound envelope it sends (the first one opens the session and authenticates the initiator; later ones bind that round's protocol payload);
* opens the wire session with the `init` envelope and later sends the cryptographic commitment payload (`msg1` in PSI);
* **computes and learns the final result** locally and captures it in a [`PrivacyResultDirective`](directives.md);
* drives session lifecycle (timeouts, retries, cancellation).

You can think of the initiator as the "querying side" — the one with a question it wants answered against a counterparty's data.

### `ap3_receiver`

The agent that **participates** in an operation initiated by someone else. In PSI, the receiver is more accurately a **service provider**: it holds the private dataset against which the initiator wants to run a computation, and it actively participates in every cryptographic round.

Receiver responsibilities:

* publish signed [commitments](commitments.md) describing the dataset shape it is willing to compute against;
* validate every incoming `PrivacyIntentDirective` (signature, expiry, replay nonce, supported operation, declared participants, payload binding);
* contribute its half of the contributory session_id (`sid_1`) and run its half of the cryptographic protocol — for PSI this means processing `msg1` against its private set and producing `msg2`;
* enforce its own policies (rate limits, payload bounds, allowed counterparties);
* (roadmap) co-sign a final result receipt for non-repudiation.

!!! note "Both sides participate in the cryptography"
    In PSI, **both** initiator and receiver run cryptographic operations on every round — the protocol is interactive. The asymmetry isn't "who computes" but "who learns the output". The initiator learns the intersection; the receiver does not. That's a property of the PSI primitive, not of being labeled "receiver".

## Are roles different for other operations?

Yes — and this is by design. Each AP3 operation defines its own role layout, because different privacy primitives have different shapes.

A few illustrative shapes you'll see as more operations land:

* **Symmetric two-party operations** (e.g. some forms of secure dot product) — both parties contribute inputs and both parties learn a single shared output. Roles still distinguish who initiates the session, but the result asymmetry of PSI doesn't apply.
* **N-party aggregation** (e.g. private federated counts) — one *aggregator* role coordinates while many *contributor* roles supply inputs.
* **Threshold / quorum operations** — a *requester* role plus a quorum of *committee* roles, where any subset above a threshold can complete the protocol.

For now, treat `ap3_initiator` / `ap3_receiver` as the PSI-specific role pair. The role catalog will grow alongside the operation catalog; see the [Roadmap](roadmap.md).

## Declaring roles in your AgentCard

Roles are advertised inside the AP3 extension `params.roles` array. An agent may advertise multiple roles if it can serve as either side:

```json
{
  "uri": "https://github.com/lfdt-ap3/ap3",
  "params": {
    "roles": ["ap3_initiator", "ap3_receiver"],
    "supported_operations": ["PSI"],
    "commitments": [ /* ... */ ]
  }
}
```

For the full schema, see [AP3 A2A Extension](extension.md).

## Compatibility, in plain terms

Two agents are AP3-compatible for a given operation when:

1. their **roles complement each other** for that operation (e.g. one is `ap3_initiator`, the other is `ap3_receiver` for PSI);
2. they share at least one **`supported_operations`** entry;
3. the receiver advertises a [commitment](commitments.md) whose shape the initiator can consume.

Compatibility is a *pre-flight check*, performed against `AgentCard` data only — no private inputs cross the wire until the [`PrivacyIntentDirective`](directives.md) is sent and accepted.
