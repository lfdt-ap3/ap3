---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Security</strong></h1>

This page covers the deployment-side security posture for AP3 agents — how to give a paying counterparty hardware-rooted assurance that your agent ran the agreed operation against the committed dataset, plus the operational guardrails that go around it. The cryptographic guarantees of the protocol itself live in [Architecture](architecture.md) and [Directives](directives.md); this page is about how you actually run the thing.

## TEE deployment

For any company using AP3, the question a paying counterparty will eventually ask is sharp:

> *"How do I know your agent is actually running the operation we agreed on, against the dataset you committed to, without quietly leaking my query or fabricating the result?"*

A signature on the result tells the counterparty *"this directive was built by the holder of your published key"*. It does **not** tell them *what code computed the result, on what data*. Closing that gap is what hardware-rooted attestation is for, and it is the recommended deployment posture for any production service provider.

### Why a TEE is the right deployment surface

From the [Architecture](architecture.md#the-two-cryptographic-building-blocks) page:

> *"Trusted Execution Environment (TEE) attestation. A complement to SMPC for cases where the workload has to run inside a hardware enclave. The enclave produces a signed attestation proving 'I ran this exact code on these encrypted inputs.' Useful when the computation is too heavy for pure SMPC or when one party wants hardware-rooted assurance."*

For a service provider specifically, a TEE gives you four things that nothing else gives at the same cost:

- **Hardware trust** — the root of trust is the enclave's manufacturer, not your operator's filesystem or your CI pipeline.
- **Runtime verification** — assurance is **per-session**, not just at build time. A counterparty can demand and verify an attestation right before the round starts.
- **Code integrity** — the attestation proves the AP3 operation binary loaded into the enclave hasn't been swapped or patched, so a malicious operator can't substitute a leakier variant.
- **Audit trail** — attestations are signed artifacts. An auditor or regulator can re-verify them after the fact alongside the signed directives and commitments.

### How a TEE composes with the rest of AP3

A service provider running in a TEE produces three layers of evidence, every session:

| Layer | Artifact | What it proves |
|---|---|---|
| Identity | AgentCard signature, [commitment](commitments.md) signature | "These keys belong to this agent and these commitments are mine." |
| Protocol | [`PrivacyIntentDirective`](directives.md) + [`PrivacyResultDirective`](directives.md) signatures | "This exact session was opened, executed, and closed by these keys." |
| Execution | TEE attestation + enclave measurement | "The result was produced by *this exact code* running inside *this exact enclave*." |

These compose: a counterparty's verification gate (see [Lifecycle](lifecycle.md)) walks the layers in order. If any layer fails, the result is refused before it influences a downstream decision.

The AP3 wire format already carries an `OperationProofs` slot on the result directive for exactly this purpose. **Today** it holds deterministic placeholder strings — see [Private APIs](operations.md#where-ap3-is-today-and-whats-experimental) — and `verify_proofs()` refuses anything below `attestation="verified"`. That is the seam where real TEE attestations will land. Designing your service provider around a TEE today means the upgrade path to first-class verified attestation is mechanical, not architectural.

### Choosing a deployment posture

[Private APIs](operations.md#how-to-choose) gives the recommendation table verbatim:

| Posture | Recommended strategies |
|---|---|
| Internal R&D / prototyping | Strategy 1 (build from source). |
| Production with moderate assurance | Strategies 1 + 2 (signed binaries from a trusted publisher). |
| **Cross-org production with sensitive data** | **Strategies 2 + 3 (signed binaries + runtime TEE attestation).** |
| Regulated / formal-assurance environments | Strategies 2 + 3 + 4 (signed + attested + formally verified core). |

A service provider that *charges* for AP3 computation — i.e. anything beyond an internal demo — falls into the third or fourth row. **TEE attestation (Strategy 3) is the recommended baseline for monetized deployments.**

!!! warning "Ecosystem maturity"
    TEE attestation is on the [Phase 1–2 Roadmap](roadmap.md) as a first-class trust-model definition; the SDK does not auto-attach attestations yet. In practice today, service providers run inside an enclave and pin the operation binary to a known measurement, then surface the attestation out-of-band (e.g. as an additional signed artifact stapled to the result metadata, or via a separate attestation endpoint). When the protocol-level slot lands, deployments that already run inside a TEE flip a flag rather than re-architecting.

## Operational checklist

Refer for more details - [Agentic Stack - Stage 1–3](agentic-stack.md#stage-1-build-what-you-ship).

**Identity & keys**

- Long-lived **signing key per agent identity**, not per process; rotation strategy with a publish-next-key/overlap-window/revocation story.
- Keep [identity keys separate from session keys](agentic-stack.md#stage-1-build-what-you-ship). Identity keys anchor your AgentCard; session keys come and go with the protocol.

**Commitments**

- Publish at least one [signed commitment](commitments.md) per dataset shape you're willing to compute against — `entry_count`, `data_freshness`, `coverage_area`, optional `data_hash`.
- Set a **realistic `expiry`** so stale claims don't keep matching against new requests.
- Treat commitments as **versioned products**: when the underlying dataset materially changes, publish a new commitment rather than mutating the old one in place.

**Policy controls**

- Inbound and outbound **allowlists** (allowed peer URLs / public keys), per-peer **rate limits** and **quotas**, **payload bounds**, **TTLs** on every session.
- Provenance/consent rules on which inputs your dataset is allowed to be used against (this is where regulated industries live).
- Decide your **security terms** up front: do you require [receiver-signed receipts](directives.md), TEE attestation, ZK proofs, audit logging? — see [Lifecycle](lifecycle.md).

**Runtime boundary**

- A stable **runtime boundary between LLM reasoning and protocol execution**. AP3 protocol traffic must stay in `Part.data`; never let it land in a prompt. The middleware/executor pattern in the [A2A + AP3 codelab](codelab-a2a-ap3.md) shows the seam.
- A stable **crypto boundary** between identity keys and protocol/session keys.

**Audit**

- Persist signed artifacts (intents, results, receipts) and the verification decisions you took on each one. Log policy-approved metadata only — *not* sensitive inputs.
- Make verification **deterministic and reproducible** so a dispute resolution can replay it months later from the stored artifacts.

## Unverified peer URLs (SSRF guard)

When a receiver accepts a session-opening envelope, it has to fetch the initiator's `AgentCard` to learn the public key it will verify the signed intent against. That fetch happens *before* any signature check — at that moment, `intent.participants[0]` is fully attacker-controlled bytes from an unauthenticated HTTP request. Without a guard, a peer could submit:

```json
{ "participants": ["http://169.254.169.254/latest/meta-data/", "<receiver_url>"], ... }
```

…and force the receiver to issue an HTTP GET against cloud metadata endpoints (AWS/GCP/Azure IMDS), RFC1918 internals, the receiver's own loopback admin ports, or arbitrary internal services — the classic CWE-918 SSRF pattern.

AP3 classifies the initiator URL by scheme + host literal **before** the card fetch:

- Schemes other than `http`/`https` are refused.
- Host literals that resolve to loopback / RFC1918 / link-local / multicast / reserved / unspecified addresses are refused.
- Reserved hostnames (`localhost`, `metadata.google.internal`, …) are refused.

A refusal surfaces as `INVALID_INITIATOR_URL` (see [AP3 A2A Extension → Error handling](extension.md#error-handling)).

The check is intentionally cheap: no DNS lookup, no side effect. DNS rebinding is out of scope — receivers that need that level of guarantee should add post-resolution validation in the HTTP client.

### `allow_private_initiator_urls` (dev only)

Local quickstarts run both sides on `127.0.0.1`, which the guard would otherwise refuse. The dev escape hatch is a constructor flag on both `PrivacyAgent` and `AP3Middleware`:

```python
# PrivacyAgent
agent = PrivacyAgent(
    ...,
    role="ap3_receiver",
    allow_private_initiator_urls=True,  # dev only — remove in production
)

# AP3Middleware
ap3 = AP3Middleware(
    identity=identity,
    operation=PSIOperation(),
    receiver_config_provider=...,
    allow_private_initiator_urls=True,  # dev only — remove in production
)
```

!!! warning "Never flip this on in production"
    A production receiver that opts into private initiator URLs is one malicious envelope away from being forced to GET its cloud metadata endpoint. Treat the flag as a build-time switch tied to a dev/local profile, not a runtime override.

The codelabs and bundled `examples/*` use this flag because they advertise loopback card URLs to each other; the per-example `__main__.py` comments call this out explicitly.