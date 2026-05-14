# ap3-functions

Protocol implementations for the [AP3](https://pypi.org/project/ap3/) (Agent Privacy-Preserving Protocol) SDK.

`ap3-functions` ships the cryptographic operation implementations (currently PSI — Private Set Intersection) that the core `ap3` SDK composes into end-to-end privacy-preserving agent workflows.

## Installation

```bash
pip install ap3-functions
```

This pulls in `ap3` automatically.

## Usage

```python
from ap3_functions import PSIOperation

initiator = PSIOperation()   # OB: customer holder
receiver  = PSIOperation()   # BB: sanction list holder

# 4-envelope flow: init → msg0 → msg1 → msg2.
# OB commits sid_0 (hidden) in init; BB reveals sid_1 in msg0; OB opens the
# commit and sends psc_msg1 in msg1. session_id = H(sid_0, sid_1).
init  = initiator.start(role="initiator", inputs={"customer_data": "John Doe,ID123"})
msg0  = receiver.receive(role="receiver", message=init["outgoing"], config={"sanction_list": [...]})
msg1  = initiator.process(session_id=init["session_id"],  message=msg0["outgoing"])
msg2  = receiver.process(session_id=msg0["session_id"],  message=msg1["outgoing"])
final = initiator.process(session_id=init["session_id"], message=msg2["outgoing"])
is_match = final["result"]["is_match"]
```

Most callers use [`PrivacyAgent.run_intent()`](https://github.com/lfdt-ap3/ap3) instead, which drives the exchange end-to-end over A2A.

> Distribution name is `ap3-functions` (hyphenated), import name is `ap3_functions` (underscored). This is standard Python packaging convention — the same way `pip install scikit-learn` gives you `import sklearn`-style decoupling.

See the [AP3 SDK docs](https://github.com/lfdt-ap3/ap3) for the full API and end-to-end examples.

## Platform support

PSI is implemented in pure Python on top of [`rbcl`](https://pypi.org/project/rbcl/) (libsodium / Ristretto255) and [`merlin_transcripts`](https://pypi.org/project/merlin-transcripts/) (Fiat–Shamir). 

It runs anywhere those wheels install — macOS, Linux, and Windows on both x86_64 and arm64.

## License

Apache-2.0
