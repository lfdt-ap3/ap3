---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>A2A and AP3</strong></h1>

This page is the **wire-level reference** for AP3 as an [Agent2Agent (A2A) extension](https://a2a-protocol.org/latest/topics/extensions/). If you're integrating AP3 into an A2A-compliant agent, this is the page that tells you exactly what to put in your `AgentCard`, what JSON shapes to expect on the wire, and how directive and error messages are structured inside A2A `DataPart`s.

## Why AP3 ships as an A2A extension

A2A is the underlying messaging protocol — a vendor-neutral way for agents to discover each other, exchange messages, and stream task updates. A2A extensions are the standard way to layer additional capabilities on top **without forking the spec**.

AP3 plugs in as one such extension. That gives you three useful properties for free:

* **Discovery is unchanged.** Counterparties find you through the standard `AgentCard`; AP3 just adds an entry under `capabilities.extensions`.
* **Protocol traffic stays in the structured lane.** AP3 payloads (commitments, intent directives, cryptographic rounds) ride inside A2A `Part.data` envelopes, not inside LLM prompts. This is critical: privacy primitives need byte-exact transport, not text re-rendering.
* **Any A2A-compliant framework works.** ADK, CrewAI, LangGraph, AutoGen and others can advertise and consume AP3 capabilities without per-framework glue.

If you're new to A2A extensions in general, skim the [A2A extension topic](https://a2a-protocol.org/latest/topics/extensions/) first; the rest of this page assumes that mental model.

### Extension URI

The URI for the AP3 extension is:
`https://github.com/lfdt-ap3/ap3`

Agents that support the AP3 extension MUST use this URI.

### Extension Declaration

Agents declare their support for extensions in their Agent Card by including `AgentExtension` objects within their `AgentCapabilities` object.

Read more about [AgentExtensions](https://a2a-protocol.org/latest/topics/extensions/) in A2A Protocol.

### AgentCard Extension Object

Agents that support the AP3 extension:

* MUST advertise their support using the Extension URI.
* MUST use the `params` object to specify the AP3 capabilities of the agent.

In the `params` object, the agent MUST specify the following:

* `roles`: The roles that the agent performs in the AP3 protocol.
* `commitments`: The data commitments that the agent declares for other agents to perform the AP3 protocol.
* `supported_operations`: The operations that the agent supports.

Read more about [Roles](roles.md), [Commitments](commitments.md) and [Operations](operations.md) in the AP3 specification.

The `params` object MUST adhere to the following JSON schema:

??? example "AP3ExtensionParameters Schema"

    ```json
    {
      "type": "object",
      "name": "AP3ExtensionParameters",
      "description": "The schema for parameters expressed in AgentExtension.params for the AP3 A2A extension.",
      "properties": {
        "roles": {
          "type": "array",
          "name": "AP3 Roles",
          "description": "The roles that this agent performs in the AP3 model.",
          "minItems": 1,
          "items": {
            "enum": [
              "ap3_initiator",
              "ap3_receiver"
            ]
          }
        },
        "commitments": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "commitment_id": "string",
              "agent_id": "string",
              "data_structure": {
                "type": "string",
                "enum": [
                  "blacklist",
                  "customer_list",
                  "transaction_log",
                  "product_catalog",
                  "supply_chain_data",
                  "financial_records",
                  "user_profiles",
                  "inventory_data"
                ]
              },
              "data_format": {
                "type": "string",
                "enum": [
                  "structured",
                  "unstructured",
                  "semi_structured",
                  "binary"
                ]
              },
              "entry_count": "number",
              "field_count": "number",
              "estimated_size_mb": "number",
              "last_updated": "string",
              "data_freshness": {
                "type": "string",
                "enum": [
                  "real_time",
                  "daily",
                  "weekly"
                ]
              },
              "coverage_area": {
                "type": "string",
                "enum": [
                  "global",
                  "regional",
                  "local"
                ]
              },
              "industry": {
                "type": "string",
                "enum": [
                  "food_delivery",
                  "retail",
                  "finance",
                  "healthcare",
                  "manufacturing",
                  "transportation",
                  "other"
                ]
              },
              "data_schema": {
                "type": "object",
                "description": "Optional full schema definition (see `DataSchema` in the SDK)."
              },
              "data_hash": {
                "type": "string",
                "description": "Optional integrity hash of the committed dataset (recommended when using CommitmentMetadataSystem)."
              },
              "expiry": {
                "type": "string",
                "description": "Optional expiry time in ISO 8601 format."
              },
              "signature": {
                "type": "string",
                "description": "Optional base64 signature over the commitment fields (recommended when using CommitmentMetadataSystem)."
              }
            }
          }
        },
        "supported_operations": {
          "type": "array",
          "items": {
            "enum": [
              "PSI"
            ]
          }
        }
      },
      "required": [
        "roles",
        "commitments",
        "supported_operations"
      ]
    }
    ```

### Example AgentCard with AP3 extension

```json
{
    "name": "XYZ Agent",
    "url": "http://localhost:10001/",
    "version": "1.0.0",
    "description": "Perform secure operations",
    "preferredTransport": "JSONRPC",
    "capabilities": {
        "extensions": [
            {
                "uri": "https://github.com/lfdt-ap3/ap3",
                "description": "AP3 extension for secure collaboration",
                "params": {
                    "roles": [
                        "ap3_initiator", "ap3_receiver"
                    ],
                    "supported_operations": [
                        "PSI"
                    ],
                    "commitments": [
                        {
                            "commitment_id": "xyz_data_commitment_v1",
                            "agent_id": "xyz-agent",
                            "data_structure": "blacklist",
                            "data_format": "structured",
                            "entry_count": 10000,
                            "field_count": 5,
                            "estimated_size_mb": 4.8,
                            "last_updated": "2025-01-01",
                            "data_freshness": "real_time",
                            "coverage_area": "global",
                            "industry": "manufacturing"
                        }
                    ]
                },
                "required": true
            }
        ],
        "streaming": true
    }
}
```

## AP3 Directives

AP3 directives are used to structure privacy-preserving computations:
* `PrivacyIntentDirective`: The intent directive is used to declare the computation to be performed.
* `PrivacyResultDirective`: The result directive is used to contain the computation result with cryptographic proofs.

Read more about [Directives](directives.md) in the AP3 specification.

### Privacy Intent Directive Message

To provide an `PrivacyIntentDirective`, the agent MUST create a `PrivacyIntentDirective` Message. A `PrivacyIntentDirective` Message is an A2A Message profile with the following requirements.

The Message MUST contain a DataPart that contains a key of `ap3.directives.PrivacyIntentDirective` and a value that adheres to the `PrivacyIntentDirective` schema.

??? example "PrivacyIntentDirective Schema"

    ```json
    {
      "type": "object",
      "name": "PrivacyIntentDirective",
      "description": "The schema for PrivacyIntentDirective messages.",
      "properties": {
        "ap3_session_id": {
          "type": "string",
          "description": "Unique identifier for this session"
        },
        "intent_directive_id": {
          "type": "string",
          "description": "Unique identifier for this privacy intent"
        },
        "operation_type": {
          "type": "string",
          "description": "Type of privacy-preserving operation (PSI)"
        },
        "participants": {
          "type": "array",
          "description": "Exactly two participants: [initiator_url, receiver_url]",
          "minItems": 2,
          "maxItems": 2,
          "items": {
            "type": "string"
          }
        },
        "nonce": {
          "type": "string",
          "description": "Initiator-chosen fresh value for anti-replay (one per signed intent)"
        },
        "payload_hash": {
          "type": "string",
          "description": "SHA-256 hex of the envelope's protocol payload this intent rides on. Each initiator→receiver envelope carries its own intent with its own payload_hash."
        },
        "expiry": {
          "type": "string",
          "description": "Expiry time in ISO 8601 format"
        },
        "signature": {
          "type": "string",
          "description": "Base64 Ed25519 signature over the canonical directive body"
        }
      },
      "required": [
        "ap3_session_id",
        "intent_directive_id",
        "operation_type",
        "participants",
        "nonce",
        "payload_hash",
        "expiry"
      ]
    }
    ```

Below example shows the JSON object of a `PrivacyIntentDirective` Message.

```json
{
  "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "contextId": "supply-chain-optimization-context",
  "taskId": "cost-optimization-task-001",
  "role": "agent",
  "parts": [
    {
      "kind": "data",
      "data": {
        "ap3.directives.PrivacyIntentDirective": {
          "ap3_session_id": "session_id",
          "intent_directive_id": "pi_12345",
          "operation_type": "PSI",
          "participants": [
            "https://manufacturer.example",
            "https://supplier.example"
          ],
          "nonce": "5ce1a8f9...",
          "payload_hash": "9f1ab2c4e7d8...",
          "expiry": "2026-06-15T10:00:00Z",
          "signature": "MEUCIQDx..."
        }
      }
    }
  ]
}
```

### Privacy Result Directive Message

To provide a `PrivacyResultDirective`, the agent MUST create a `PrivacyResultDirective` Message. A `PrivacyResultDirective` Message is an A2A Message profile with the following requirements.

The Message MUST contain a DataPart that contains a key of `ap3.directives.PrivacyResultDirective` and a value that adheres to the `PrivacyResultDirective` schema.

??? example "PrivacyResultDirective Schema"

    ```json
    {
      "type": "object",
      "name": "PrivacyResultDirective",
      "description": "The schema for PrivacyResultDirective messages.",
      "properties": {
        "ap3_session_id": {
          "type": "string",
          "description": "Unique identifier for this session"
        },
        "result_directive_id": {
          "type": "string",
          "description": "Unique identifier for this result directive"
        },
        "result_data": {
          "type": "object",
          "description": "Encoded result data and metadata",
          "properties": {
            "encoded_result": "string",
            "result_hash": "string",
            "metadata": {
              "type": "object",
              "description": "Metadata about the result"
            }
          }
        },
        "proofs": {
          "type": "object",
          "description": "Cryptographic proofs of correctness and privacy"
        },
        "signature": {
          "type": "string",
          "description": "Cryptographic signature of the initiator agent"
        }
      },
      "required": [
        "ap3_session_id",
        "result_directive_id",
        "result_data",
        "proofs"
      ]
    }
    ```

Below example shows the JSON object of a `PrivacyResultDirective` Message.

```json
{
  "messageId": "c3d4e5f6-g7h8-9012-cdef-345678901234",
  "contextId": "supply-chain-optimization-context",
  "taskId": "cost-optimization-task-001",
  "role": "agent",
  "parts": [
    {
      "kind": "data",
      "data": {
        "ap3.directives.PrivacyResultDirective": {
          "ap3_session_id": "session_id",
          "result_directive_id": "rm_11111",
          "result_data": {
            "encoded_result": "0x1a2b3c4d5e6f...",
            "result_hash": "sha256:789abc...",
            "metadata": {
              "computation_time": "45.2s",
              "elements_processed": 127
            }
          },
          "proofs": {
            "correctness_proof": "0x9f8e7d6c5b4a...",
            "privacy_proof": "0x3f2e1d0c9b8a...",
            "verification_proof": "0x7e6d5c4b3a29..."
          },
          "signature": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjIwMjQwOTA..."
        }
      }
    }
  ]
}
```

## Error Handling

AP3 agents MUST handle error conditions gracefully:

### Privacy Protocol Errors Message

To provide a `PrivacyProtocolError`, the agent MUST create a `PrivacyProtocolError` Message. A `PrivacyProtocolError` Message is an A2A Message profile with the following requirements.

The Message MUST contain a DataPart that contains a key of `ap3.errors.PrivacyProtocolError` and a value that adheres to the `PrivacyProtocolError` schema.

??? example "PrivacyProtocolError Schema"

    ```json
    {
      "type": "object",
      "name": "PrivacyProtocolError",
      "description": "The schema for PrivacyProtocolError messages.",
      "properties": {
        "error_code": {
          "type": "string",
          "description": "Machine-readable error code"
        },
        "error_message": {
          "type": "string",
          "description": "Human-readable error message"
        },
        "operation_type": {
          "type": "string",
          "description": "Operation directive that failed"
        },
        "recovery_options": {
          "type": "array",
          "description": "Available recovery options",
          "items": {
            "type": "string"
          }
        },
        "timestamp": {
          "type": "string",
          "description": "Timestamp when the error occurred"
        }
      },
      "required": [
        "error_code",
        "error_message"
      ]
    }
    ```

Below example shows the JSON object of a `PrivacyProtocolError` Message.

```json
{
  "messageId": "error-001",
  "contextId": "computation-context",
  "taskId": "failed-computation",
  "role": "agent",
  "parts": [
    {
      "kind": "data",
      "data": {
        "ap3.errors.PrivacyProtocolError": {
          "error_code": "PROTOCOL_FAILURE",
          "error_message": "MPC protocol failed due to malicious participant",
          "operation_type": "PSI",
          "timestamp": "2025-01-15T10:30:00Z"
        }
      }
    }
  ]
}
```

### Receiver error codes

A receiver that refuses an inbound envelope replies with a `PrivacyError` whose `error_code` is one of the values below. Initiators must treat any of these as terminal for the session.

| `error_code` | When it fires | What it means for the initiator |
|---|---|---|
| `UNSUPPORTED_WIRE_VERSION` | `envelope.ap3_wire_version` is not in the receiver's `SUPPORTED_WIRE_VERSIONS`. | Upgrade or downgrade to a wire version both peers speak. |
| `MISSING_INTENT` | First-round envelope arrived without a `privacy_intent`. | Initiator bug — always attach an intent to the session-opening envelope. |
| `INVALID_INTENT` | Intent failed pydantic validation, had ≠ 2 participants, or contained an empty URL. | Inspect the intent shape; the receiver also runs a defence-in-depth backstop on `participants` length. |
| `INVALID_INITIATOR_URL` | `participants[0]` points at a scheme/host the receiver refuses to fetch without authentication (see [Unverified peer URLs (SSRF guard)](security.md#unverified-peer-urls-ssrf-guard)). | Use a routable public URL for the initiator's card. For local dev, flip `allow_private_initiator_urls=True` on the receiver. |
| `WRONG_RECEIVER` | `participants[1]` does not match this receiver's canonical `self_url`. | Confirm the URL the initiator signed against matches the receiver's advertised card URL (trailing slash, port, scheme — `normalize_url` collapses the common cases). |
| `BAD_SIGNATURE` | Intent signature does not verify against the initiator's published key, even after one forced card refresh. | Likely key rotation or wrong key on the card. Republish the card and retry. |
| `INTENT_SESSION_MISMATCH` | `intent.ap3_session_id` does not match `envelope.session_id`. | Intent must be bound to *this* envelope's session ID. |
| `INTENT_OPERATION_MISMATCH` | `intent.operation_type` does not match the receiver's operation. | Initiator targeted the wrong operation on this receiver. |
| `INTENT_REJECTED` | `intent.validate_directive()` returned false (expired, empty nonce, malformed `payload_hash`, etc.). | Read `error_message` for the specific failure. |
| `INTENT_PAYLOAD_MISMATCH` | `intent.payload_hash` does not equal the hash of `envelope.payload`. | Either the intent or the payload was modified after signing — refuse and start over. |
| `REPLAY` | The receiver has already processed this `(initiator_pubkey, session_id, intent_id, nonce, payload_hash)` tuple. | Fresh nonce per intent; do not reuse signed intents across rounds. |
| `INCOMPATIBLE_PEER` | Compatibility scorer returned below `MIN_COMPAT_SCORE`. | Inspect `error_message` for the failing dimension (roles / supported_operations / commitments). |
| `SESSION_EXPIRED` | A subsequent envelope arrived for a session the receiver no longer holds. | Session was cleared (timeout, restart, prior `done`). Open a new session. |
| `OPERATION_ERROR` | The underlying `Operation.receive` / `Operation.process` raised. | Internal failure on the receiver — message is intentionally generic to avoid leaking state. Retry with backoff or surface to the operator. |