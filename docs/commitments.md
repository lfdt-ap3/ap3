---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>Commitments</strong></h1>

A **commitment** is a small, signed piece of public metadata in which an agent declares: *"I have a dataset of this shape, this size, and this freshness, and I am willing to compute against it."* It is the AP3 analog of an API contract — except the API in question is "let me run a privacy-preserving computation against my data".

The single most important thing a commitment is trying to do is this:

> **Prove that the agent actually has the dataset it claims to have**, so a counterparty can decide whether to engage *before* any private computation begins.

Everything else in this page — the schema, the signature, the metadata fields, the discovery flow — exists to support that one goal.

!!! warning "Today, commitments are *self-asserted*"
    The current implementation lets an agent sign whatever shape it wants. The signature proves the agent committed to a specific claim and lets you detect tampering after the fact, but it does **not** by itself prove the agent really holds the data described. That gap is closed by **proof of computation**, which is on the [Roadmap](roadmap.md) and tracked under [Private APIs](operations.md). Until then, commitments should be treated as a *strong hint* paired with reputation, allowlists, or off-protocol assurances (e.g. legal contracts, [W3C Verifiable Credentials](w3vc-ap3.md) issued by an auditor).

## The data disclosure dilemma

Two organizations want to evaluate a privacy-preserving collaboration. Before they spend cycles on a real computation, each side wants to know roughly what the other has. But neither side wants to leak it. The traditional options are bad:

* **Reveal too much** — share actual data samples (privacy violation, regulatory risk).
* **Reveal too little** — share nothing, force "blind" engagement (no basis for a go/no-go decision).

Commitments are the middle ground. They reveal *enough metadata to make an informed decision*, none of the underlying records, and they are signed so the metadata is hard to fake silently.

## Commitment vs. Data schema

* An **AP3 `DataSchema`** has — fields, format, optional constraints. It says *what an entry in the committed dataset looks like*. It is one piece of a commitment, **not the whole thing**.
* An **AP3 `CommitmentMetadata`** wraps the schema and adds **business-relevant context that a SQL schema does not carry**: the entry count, freshness, coverage area, industry, an integrity hash of the dataset, an expiry, and a signature.

```text
┌──────────────────── CommitmentMetadata ────────────────────┐
│  agent_id, commitment_id                                   │
│  ┌──────────── DataSchema (≈ SQL schema) ──────────────┐   │
│  │   structure (BLACKLIST, CUSTOMER_LIST, ...)         │   │
│  │   format    (STRUCTURED, BINARY, ...)               │   │
│  │   fields    [name, id, address, ...]                │   │
│  │   constraints, metadata                             │   │
│  └─────────────────────────────────────────────────────┘   │
│  entry_count, field_count, estimated_size_mb              │
│  data_freshness, last_updated, coverage_area, industry    │
│  data_hash, expiry                                        │
│  signature  ← over the whole thing                        │
└────────────────────────────────────────────────────────────┘
```

A schema tells you *how to parse a row*; a commitment tells you *whether to engage with a dataset at all*.

## Why commitments are signed

Two reasons, in order of importance:

1. **Tamper-evidence and auditability.** A commitment is a public claim the agent stands behind. Signing it makes the claim attributable: a third party can verify, after the fact, that this exact metadata was published by this exact agent. If a dispute arises later — "you said you had a daily-refreshed blacklist of 10,000 entries" — the signed commitment is the artifact you point to.
2. **Foundation for reputation, scoring, and incentives.** AP3's longer-term vision is an ecosystem where commitments accumulate reputation: agents that consistently honor their commitments earn trust, agents that misrepresent get penalized. None of that works without signed, attributable claims as the substrate. Today this is a foundation; the scoring/incentives layer is on the [Roadmap](roadmap.md).

A signature does **not** prove the underlying data exists or matches the claim. As noted above, that's the job of proof-of-computation work, which is currently experimental.

## What's revealed (and what isn't)

Commitments deliberately reveal only:

* Data **structure** and **format** (e.g. "structured blacklist with 5 fields").
* **Entry count** and an **estimated size**.
* **Freshness** and **last updated** timestamp.
* **Coverage area** and **industry** (so a counterparty can match scope).
* An optional **integrity hash** of the dataset (so a follow-up proof-of-computation can be bound to it).

!!! note "What is NOT in a commitment"
    A commitment never contains actual data records, individual entries, or any field values. The shape and metadata are public; the contents are private.

## Mandatory vs. optional fields

The Pydantic model for a commitment lives at `ap3.types.core.CommitmentMetadata`. Here is the field-by-field breakdown for developers:

### Required fields

These must be present on every commitment:

| Field | Type | What it means |
|---|---|---|
| `commitment_id` | string | Stable identifier for this commitment, chosen by the agent (e.g. `"psi_blacklist_v3"`). Used to reference the commitment in directives and logs. |
| `agent_id` | string | The agent that owns and signs this commitment. |
| `data_structure` | enum | High-level shape: `blacklist`, `customer_list`, `transaction_log`, `product_catalog`, `supply_chain_data`, `financial_records`, `user_profiles`, `inventory_data`. Used for compatibility matching. |
| `data_format` | enum | Encoding shape: `structured` (JSON/CSV/DB rows), `unstructured` (free text), `semi_structured` (mixed), `binary` (media/encoded). |
| `entry_count` | int | Number of records in the dataset. Helps the counterparty estimate computation cost and statistical usefulness. |
| `field_count` | int | Number of fields per entry. |
| `estimated_size_mb` | float | Approximate dataset size in megabytes. Useful for the counterparty to estimate transfer/compute cost; mostly informational. |
| `last_updated` | string (ISO 8601) | When the dataset was last refreshed. Pairs with `data_freshness` to ground the freshness claim. |
| `data_freshness` | enum | Update cadence: `real_time`, `daily`, `weekly`. Lets a counterparty filter for "fresh enough" datasets. |
| `industry` | enum | Industry the dataset belongs to: `food_delivery`, `retail`, `finance`, `healthcare`, `manufacturing`, `transportation`, `other`. Compatibility hint. |

### Optional fields

These are recommended in production but not required:

| Field | Type | What it means |
|---|---|---|
| `coverage_area` | enum | Geographic scope: `global`, `regional`, `local`. Defaults to `global`. Lets a counterparty filter to "agents whose data overlaps my region of interest" — for example, an EU bank only wants to engage with EU-coverage datasets for GDPR reasons. |
| `data_schema` | `DataSchema` | The full schema (fields, format, constraints). Required only if the operation needs to type-check inputs against it. |
| `data_hash` | string | A hash of the dataset (e.g. `"sha256:abc123…"`) used as an *integrity anchor*. A future proof-of-computation can prove "I computed against the dataset whose hash is X". |
| `expiry` | string (ISO 8601) | When the commitment becomes stale. Counterparties should reject expired commitments. |
| `signature` | string | Base64 signature over the canonical commitment payload. Required if you want auditability — `CommitmentMetadataSystem.create_commitment()` populates this for you. |

!!! tip "Why include `estimated_size_mb` if it's not load-bearing?"
    It's metadata that helps the counterparty plan: a multi-GB dataset has very different cost characteristics than a few-KB one. It is informational only, never part of any cryptographic proof, and an agent is free to omit it (or keep it coarse) if size itself is sensitive.

## How it works end to end

The example below uses two agents: **XYZ**, who holds a blacklist of 10,000 entries with 5 fields, and **ABC**, who is shopping for a partner whose blacklist matches certain criteria.

### 1. Creating a commitment — XYZ agent

`CommitmentMetadataSystem.create_commitment()` handles canonical serialization, signing, and validation in one call.

```python
from ap3.services import CommitmentMetadataSystem
from ap3.types.core import DataSchema, DataStructure, DataFormat

system = CommitmentMetadataSystem()

xyz_data_commitment = system.create_commitment(
    agent_id="xyz_agent",
    data_schema=DataSchema(
        structure=DataStructure.BLACKLIST,
        format=DataFormat.STRUCTURED,
        fields=["person_id", "name", "phone", "reason", "date_added"],
    ),
    entry_count=10000,
    data_hash="sha256:abc123...",
)
```

### 2. The commitment is signed automatically

The returned `CommitmentMetadata` already has its `signature` field populated. There's no separate "sign" step you have to remember:

```json
{
  "commitment_id": "commit_...",
  "signature": "xyz_signature_12345"
}
```

If you build commitments by hand for testing, you can sign them later via the same system.

### 3. Public metadata — XYZ agent

The complete object can be safely embedded in the public `AgentCard`:

```json
{
  "commitment_id": "commit_...",
  "agent_id": "xyz_agent",
  "data_structure": "blacklist",
  "data_format": "structured",
  "entry_count": 10000,
  "field_count": 5,
  "estimated_size_mb": 4.8,
  "last_updated": "2025-01-20T10:00:00Z",
  "data_freshness": "daily",
  "coverage_area": "global",
  "industry": "finance",
  "signature": "xyz_signature_12345"
}
```

Reading it: *"xyz_agent holds a structured blacklist of 10,000 records with 5 fields each, refreshed daily, with global geographic scope, in the food-delivery industry. The whole claim is signed and tamper-evident."*

### 4. Discovery and filtering — ABC agent

The other side queries the system for commitments matching what it needs:

```python
from ap3.services import CommitmentMetadataSystem
from ap3.types.core import DataStructure

system = CommitmentMetadataSystem()

suitable_partners = system.search_commitments(
    data_structure=DataStructure.BLACKLIST,
    min_entry_count=5000,
)

for partner in suitable_partners:
    evaluation = evaluate_partner(partner)
    print(f"Agent: {partner.agent_id}")
    print(f"Entry Count: {partner.entry_count:,}")
```

### 5. Evaluation and scoring — ABC agent

Scoring is application-defined. A typical heuristic combines size, freshness, and coverage:

```python
def evaluate_partner(partner_metadata):
    score = 0.0

    if partner_metadata.entry_count >= min_required:
        score += 50.0

    freshness_scores = {
        "real_time": 30.0,
        "daily": 25.0,
        "weekly": 15.0,
    }
    score += freshness_scores.get(partner_metadata.data_freshness, 0.0)

    if partner_metadata.estimated_size_mb <= 100:
        score += 15.0

    return min(score, 100.0)
```

## Custom commitments

The fixed enums (`DataStructure`, `Industry`, `CoverageArea`, …) cover common scenarios but they are explicitly **not** the long-term ceiling of what you can express. As AP3 matures, the protocol will let agents declare commitments built on **custom data schemas** — domain-specific shapes the core enums don't cover.

This is a high-level exploration of where the commitment surface is heading. Treat the patterns below as forward-looking; today, you can already encode most of them by leveraging the optional `DataSchema` and the `metadata` / `constraints` dicts within it.

### Why custom commitments matter

Real-world datasets rarely line up perfectly with eight pre-defined structures. A few examples:

* **Healthcare** — a hospital might want to commit to "ICD-10-coded patient encounters with structured outcomes", which is not just `user_profiles` or `transaction_log`.
* **Geospatial** — a logistics company's "delivery telemetry" is structured, but the meaningful commitment is over geo-bounded trajectories, not generic records.
* **Vector / embedding stores** — for AI workloads, two parties may want to compute similarities over committed embedding spaces.
* **Event streams** — append-only logs with strong ordering guarantees behave differently from snapshot tables.

A custom commitment lets the agent describe these shapes precisely, so a counterparty can match on **what actually matters** for the workload.

### What a custom commitment looks like

Today, you can express custom shapes by populating the optional `DataSchema` with structured `fields`, `constraints` and `metadata`:

```python
from ap3.types.core import DataSchema, DataStructure, DataFormat

custom_schema = DataSchema(
    # Pick the closest existing structure today; first-class custom
    # structures are tracked on the roadmap.
    structure=DataStructure.USER_PROFILES,
    format=DataFormat.STRUCTURED,
    fields=["encounter_id", "patient_pseudonym", "icd10_code", "outcome", "timestamp"],
    constraints={
        "icd10_code": {"pattern": r"^[A-Z][0-9]{2}(\.[0-9]{1,2})?$"},
        "outcome": {"enum": ["recovered", "ongoing", "deceased", "transferred"]},
        "timestamp": {"format": "iso8601"},
    },
    metadata={
        "namespace": "health.icd10.encounters.v1",
        "purpose": "joint outcome statistics across hospitals",
        "regulatory_class": "phi-pseudonymized",
    },
)
```

The `namespace` is the convention to watch: it's how two agents in different organizations can agree they're talking about the *same* custom shape — a stable, versioned identifier that both sides recognize. Think of it as a content-type for commitments.

### What's coming next

Looking forward, the commitment surface is expected to support:

* **Schema registries** — a shared place where namespaces resolve to canonical schema definitions, so agents don't need to ship the full schema in every card.
* **Schema versioning** — backward-compatible evolution of a custom shape over time.
* **Constraint vocabularies** — standard ways to express things like "values are in this range", "timestamps are monotonic", "field is a hashed identifier with this hash function", so a counterparty can verify operability without reading prose.
* **Proof-bound schemas** — schemas whose `data_hash` is verifiable through proof-of-computation, closing the loop on "did you actually have what you said?".

If you have an in-flight use case that doesn't fit the current enums, the recommended approach is: pick a `data_structure` that's the closest fit, populate `DataSchema` with the precise shape, namespace it via `metadata`, and follow the [Roadmap](roadmap.md) for first-class custom commitment support.

## Roadmap

* Commitments will evolve into a **trusted registry** that other agents can query to find suitable partners for privacy-preserving computations.
* **Automated scoring and evaluation** of commitments will be added to the protocol.
* **Enforcement and reward** systems will incentivize agents to honor — and accurately describe — their commitments.
* **Proof of computation** will close the gap between "I claim I have this data" and "I can cryptographically demonstrate I have this data" — see [Private APIs](operations.md) and the [Roadmap](roadmap.md) for the current status.
