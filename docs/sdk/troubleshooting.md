# Troubleshooting

This guide covers common issues you might encounter while using the AP3 SDK and their solutions.

## Installation Issues

### Python Version Mismatch

**Problem:** `ERROR: Package requires a different Python: 3.10.0 not in '>=3.11,<3.14'`

**Solution:**

```bash
# Check your Python version
python --version  # Should be 3.11.x or later

# Install Python 3.11 if needed
# macOS (Homebrew)
brew install python@3.11

# Ubuntu/Debian
sudo apt-get install python3.11

# Create venv with correct version
python3.11 -m venv .venv
source .venv/bin/activate
```

### PSI dependency loading errors

**Problem:** `ModuleNotFoundError: No module named 'rbcl'` or `merlin_transcripts`

`ap3-functions` is pure Python but depends on `rbcl` (libsodium / Ristretto255) and `merlin_transcripts`. Both ship prebuilt wheels for macOS / Linux / Windows on x86_64 + arm64. If pip can't find a wheel for your platform it will try to build from source — make sure a C toolchain and `libsodium` are available, or upgrade pip.

**Solution:**

```bash
pip install --upgrade pip
pip install ap3-functions
python -c "import rbcl, merlin_transcripts; print('PSI deps OK')"
```

If install still fails, report your platform / arch / Python version to support@silencelaboratories.com.

## Configuration Issues

### API Key Not Found

**Problem:** `ValueError: GOOGLE_API_KEY environment variable not set`

**Solution:**

```bash
# 1. Create .env file
cat > .env << 'EOF'
GOOGLE_API_KEY="your-key-here"
EOF
```

```python
# 2. Load it in your code
from dotenv import load_dotenv
load_dotenv()

# 3. Verify it's loaded
import os
print("Key loaded!" if os.getenv('GOOGLE_API_KEY') else "Key missing!")
```

### Agent Connection Refused

**Problem:** `httpx.ConnectError: [Errno 61] Connection refused`

**Solution:**

1. **Check agent is running:**
   ```bash
   # Check if process is listening
   lsof -i :10002  # PSI Initiator
   lsof -i :10003  # PSI Receiver
   lsof -i :8080   # Host
   ```

2. **Verify correct URL:**
   ```python
   import httpx

   try:
       response = httpx.get("http://localhost:10002/")
       print(f"Agent responding: {response.status_code}")
   except httpx.ConnectError:
       print("❌ Agent not running or wrong URL")
   ```

3. **Check firewall:**
   ```bash
   # macOS - allow incoming connections
   # System Settings → Network → Firewall

   # Linux
   sudo ufw allow 10002
   sudo ufw allow 10003
   sudo ufw allow 8080
   ```

## PSI Protocol Issues

### `ProtocolError` from `PSIOperation`

PSI raises `ap3_functions.exceptions.ProtocolError` for any recoverable protocol-level failure: empty sanction list, missing customer data, missing receiver state, malformed payload, wrong phase, etc. The message describes the failure.

**Common causes:**

1. **Empty `sanction_list`:** the receiver config provider must return a non-empty list.
   ```python
   ProtocolError: Protocol error at round 0: sanction_list must be non-empty
   ```

2. **Missing `customer_data` on the initiator:** pass it via `inputs`.
   ```python
   ProtocolError: Protocol error: PSI requires customer_data
   ```

3. **Sanction list rows not matching the input format:** PSI matching is *exact* and case-sensitive over the canonical string representation of each row. Both sides must agree on how rows are stringified (e.g. `"Name,ID,Address"`). If you load from a database, make sure the field order is identical on both sides.

### Session Not Found

**Problem:** `KeyError: Unknown session: <session_id>`

**Cause:** Wrong session ID passed to `process()`, or session already completed.

**Solution:** drive the protocol through `PrivacyAgent.run_intent(...)` end-to-end — it manages session IDs and the 4-envelope flow for you. 

If you need to drive it directly, the wire flow is:

```python
from ap3_functions import PSIOperation

initiator = PSIOperation()   # OB: holds the customer to check
receiver  = PSIOperation()   # BB: holds the sanction list

sanction_list = ["Alice Smith,ID001,1 Main St", "Bob Jones,ID002,2 Oak Ave"]

# 1. OB picks sid_0, commits to it under a random blind, and sends the commit.
init = initiator.start(role="initiator", inputs={"customer_data": "John Doe,ID123,123 Main St"})

# 2. BB receives the commit, picks sid_1, returns msg0 = sid_1 (in the clear).
msg0 = receiver.receive(role="receiver", message=init["outgoing"], config={"sanction_list": sanction_list})

# 3. OB opens the commit (revealing sid_0 + blind), derives session_id = H(sid_0, sid_1),
#    and sends msg1 = sid_0 ‖ blind ‖ psc_msg1.
msg1 = initiator.process(session_id=init["session_id"], message=msg0["outgoing"])

# 4. BB runs PSC, returns msg2.
msg2 = receiver.process(session_id=msg0["session_id"], message=msg1["outgoing"])

# 5. OB finalizes.
final = initiator.process(session_id=init["session_id"], message=msg2["outgoing"])
is_match = final["result"]["is_match"]
```

## Agent Communication Issues

### `INVALID_INITIATOR_URL` from a localhost run

**Problem:** Initiator gets `PrivacyProtocolError: [INVALID_INITIATOR_URL] initiator_url host 'localhost' resolves to a local target` when both sides run on the same machine.

**Cause:** The receiver's SSRF guard refuses to fetch the initiator's AgentCard from loopback, RFC1918, link-local, multicast, or cloud-metadata addresses *before* any signature check — because that URL is fully attacker-controlled at that point. See [Unverified peer URLs (SSRF guard)](../security.md#unverified-peer-urls-ssrf-guard) for the threat model.

**Solution (dev/local only):** Opt the receiver into the dev escape hatch:

```python
# PrivacyAgent
PrivacyAgent(..., role="ap3_receiver", allow_private_initiator_urls=True)

# AP3Middleware
AP3Middleware(identity=..., operation=..., allow_private_initiator_urls=True)
```

!!! danger "Never set this in production"
    A production receiver with `allow_private_initiator_urls=True` is one malicious envelope away from being SSRF'd into its cloud metadata endpoint. Tie the flag to a dev-only build profile.

**Production fix:** Make sure the initiator's advertised card URL is a routable public address (HTTPS, real DNS).

### Message Not Received

**Problem:** Agent doesn't respond to messages

**Solution:**

1. **Check agent logs:**
   ```bash
   # PSI demo (Docker)
   make logs

   # PSI demo (local)
   # Check terminal output for each agent process
   ```

2. **Verify message format:**
   ```python
   # Correct A2A message format
   from a2a.types import Message, Part, Role, SendMessageRequest

   msg = Message(role=Role.ROLE_USER, message_id=message_id)
   msg.context_id = context_id
   msg.parts.append(Part(text=json.dumps(protocol_data)))
   message_request = SendMessageRequest(message=msg)
   ```

3. **Check agent card:**
   ```python
   async with httpx.AsyncClient() as client:
       resolver = A2ACardResolver(client, agent_url)
       card = await resolver.get_agent_card()
       print(f"Agent: {card.name}, URL: {card.url}")
   ```

## Performance Issues

### Slow Protocol Execution

**Problem:** PSI takes too long

**Common Causes:**

1. **Network latency** — Use local agents for testing
2. **Large dataset** — PSI scales with sanction list size
3. **Debug logging** — Disable verbose logging in production

**Solution:**

```python
import logging

# Production: Only warnings and errors
logging.basicConfig(level=logging.WARNING)

# Development: Info level
logging.basicConfig(level=logging.INFO)
```

### High Memory Usage

**Problem:** Python process uses excessive memory

**Solution:**

```python
# Reuse PSIOperation instance across requests — sessions are cleaned up
# automatically when done=True
psi = PSIOperation()
# ... use psi for multiple requests ...
```

## Gemini API Issues

### Rate Limit Exceeded

**Problem:** `429 Too Many Requests`

**Solution:**

```python
import time
from google.api_core import retry

@retry.Retry(predicate=retry.if_exception_type(Exception))
def call_with_retry():
    # Your Gemini API call
    pass

# Or manual backoff
for attempt in range(3):
    try:
        response = agent.process(message)
        break
    except Exception as e:
        if '429' in str(e):
            time.sleep(2 ** attempt)
        else:
            raise
```

### Quota Exhausted

**Problem:** `Resource exhausted: Quota exceeded`

**Solution:**

1. Check your quota: [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Use a different API key
3. Implement request batching
4. Switch to a lower-cost model

## Common Error Messages

### `ImportError: cannot import name 'X' from 'ap3'`

**Cause:** Incorrect import path

**Solution:**

```python
# Correct imports
from ap3_functions import PSIOperation        # ✓
from ap3.services import CommitmentMetadataSystem        # ✓
from ap3.types.directive import PrivacyIntentDirective   # ✓

# Wrong — these no longer exist
from ap3.operations.psi import SanctionCheck  # ✗ class removed
from ap3.operations.sfe import DotProduct     # ✗ SFE removed
```

### `pydantic.ValidationError: X field required`

**Cause:** Missing required field in Pydantic model

**Solution:**

```python
from ap3.types.directive import PrivacyIntentDirective

intent = PrivacyIntentDirective(
    ap3_session_id="session_123",         # required
    intent_directive_id="intent_001",     # required
    operation_type="PSI",                 # required — "PSI" only
    participants=["agent1", "agent2"],    # required — min 2 entries
    expiry="2026-12-31T23:59:59Z",        # required
    signature=None,                       # optional
)
```

### `create_commitment() missing required argument: 'data_hash'`

**Cause:** `data_hash` is required but often omitted from examples.

**Solution:**

```python
from ap3.services import CommitmentMetadataSystem
from ap3.types.core import DataSchema, DataStructure, DataFormat

system = CommitmentMetadataSystem()
commitment = system.create_commitment(
    agent_id="agent_01",
    data_schema=DataSchema(
        structure=DataStructure.BLACKLIST,
        format=DataFormat.STRUCTURED,
        fields=["name", "id", "address"],
    ),
    entry_count=5000,
    data_hash="sha256:abc123...",  # required
)
```

## Debug Mode

Enable detailed debugging:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Reduce noise from http library
logging.getLogger('httpx').setLevel(logging.WARNING)
```

## Getting Help

If you can't resolve your issue:

1. **Check Examples:** Review working examples in [`examples/`](https://github.com/lfdt-ap3/ap3/tree/main/examples) (e.g. `psi_simple`, `a2a-example`, `psi_adk_simple`)
2. **Search Issues:** [GitHub Issues](https://github.com/lfdt-ap3/ap3/issues)
3. **Contact Support:** support@silencelaboratories.com
4. **Report Bug:** Include:
   - `ap3` and `ap3-functions` versions (`pip show ap3 ap3-functions`)
   - Python version
   - Platform (macOS/Linux) and architecture (`uname -m`)
   - Full error traceback
   - Minimal reproduction code

## Diagnostic Commands

Run these to gather information for support:

```bash
# System info
python --version
pip show ap3 ap3-functions       # or: uv pip show ap3 ap3-functions
uname -a                          # Linux/macOS

# Test imports
python -c "import ap3; print(ap3.__version__)"
python -c "import ap3_functions; print(ap3_functions.__version__)"
python -c "from ap3_functions import PSIOperation; print('PSIOperation OK')"
python -c "from ap3.types.directive import PrivacyIntentDirective; print('Directives OK')"

# Verify PSI runtime deps are importable
python -c "import rbcl, merlin_transcripts; print('PSI deps OK')"
```
