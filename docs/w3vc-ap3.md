---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>W3C VC and AP3</strong></h1>

### W3C Verifiable Credentials and AP3

[W3C Verifiable Credentials (VCs)](https://www.w3.org/TR/vc-data-model-2.0/) describe **who you are and what's been said about you** in a tamper-evident, cryptographically signed format. AP3 describes **what private computation you can participate in**. The two are complementary:

- **VCs answer "is this agent allowed to talk to me?"** Examples: "this agent represents a regulated bank", "this dataset has been audited by an accredited third party", "this operator passed KYC". These can be presented at the discovery / negotiation stage, before any AP3 round runs.
- **AP3 answers "given that we're allowed to talk, can we compute on each other's data without revealing it?"** AP3 commitments and directives carry their own signatures, but they don't (and don't try to) replicate the full identity-and-attestation surface that VCs cover.

A practical pattern looks like:

1. **Identity gate (VC)** — receiver presents one or more VCs in (or alongside) its `AgentCard`: e.g. an issuer-signed credential proving regulatory status, or a credential issued by a data auditor proving the dataset was inspected.
2. **Capability gate (AP3)** — the initiator inspects the AP3 extension: roles, supported operations, signed [commitments](commitments.md). It only proceeds if the commitment shape matches what it needs.
3. **Compute (AP3)** — the parties run the AP3 [operation](operations.md) under signed [directives](directives.md). The result can itself be wrapped in a VC ("agent X attests result R for session S") so downstream consumers can verify it without re-running the protocol.

In short: VCs help you decide *who to trust before computing*; AP3 lets you *compute privately once you've decided to engage*; and AP3 results can be re-issued as VCs for downstream consumers.