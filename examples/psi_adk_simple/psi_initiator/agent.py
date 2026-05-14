"""ADK agent that can initiate AP3 PSI from chat via `ap3.a2a`.

Importing this module does NOT start the AP3 server.  The server starts
lazily on the first call to `run_psi_check`, which prevents port-binding
failures when ADK reimports the module for graph previews or session
creation.  A process-level singleton (keyed in `sys.modules`) ensures only
one server is ever started even across multiple module imports.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from ap3.a2a import PrivacyAgent
from ap3.signing.primitives import generate_keypair
from ap3.types import (
    CommitmentMetadata,
    DataFormat,
    DataFreshness,
    DataStructure,
    Industry,
)
from ap3_functions import PSIOperation

_KEYS_PATH = Path(__file__).parent / "ap3_keys.json"
# Sentinel key — survives module re-imports inside the same process.
_RUNTIME_KEY = "__ap3_psi_initiator_runtime__"


def _load_or_create_keys(path: Path) -> tuple[bytes, bytes]:
    if path.exists():
        raw = json.loads(path.read_text())
        return bytes.fromhex(raw["private_key_hex"]), bytes.fromhex(raw["public_key_hex"])
    private_key, public_key = generate_keypair()
    path.write_text(
        json.dumps(
            {"private_key_hex": private_key.hex(), "public_key_hex": public_key.hex()},
            indent=2,
        )
    )
    return private_key, public_key


def _format_psi_result(raw: str, customer_row: str, peer_url: str) -> str:
    s = (raw or "").strip()
    if not s:
        return f"PSI check against {peer_url} returned no result for: {customer_row}"
    return f"PSI check against {peer_url} completed.\nCustomer: {customer_row}\nResult: {s}"


class _InitiatorRuntime:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._agent: Optional[PrivacyAgent] = None
        self._started = threading.Event()
        self._start_error: Optional[BaseException] = None

    def ensure_started(self) -> None:
        if self._thread and self._thread.is_alive() and self._loop and self._agent:
            return
        self._started.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="ap3-psi-initiator", daemon=True)
        self._thread.start()
        self._started.wait(timeout=10)
        if self._start_error:
            err = self._start_error
            if isinstance(err, SystemExit):
                # uvicorn calls sys.exit(1) on port-binding failure.
                # Re-raising SystemExit in the main thread kills the process.
                # Convert to OSError so callers can catch it normally.
                port = int(os.getenv("AP3_PORT", "10002"))
                raise OSError(
                    f"AP3 server could not start on port {port} (uvicorn exit {err.code}). "
                    f"Port may be in use. Free it: lsof -ti:{port} | xargs kill"
                )
            raise err

    def submit(self, coro) -> Future:
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._serve_forever())
        except SystemExit as e:
            # uvicorn raises SystemExit on port-binding failure.
            # Store it but do NOT re-raise — re-raising SystemExit in a daemon
            # thread is harmless, but ensure_started() would then re-raise it
            # in the main thread, killing the entire ADK server process.
            self._start_error = e
            self._started.set()
        except BaseException as e:
            self._start_error = e
            self._started.set()
            raise

    async def _serve_forever(self) -> None:
        port = int(os.getenv("AP3_PORT", "10002"))
        card_url = os.getenv("CARD_URL", f"http://localhost:{port}")
        host = os.getenv("HOST", "127.0.0.1")
        private_key, public_key = _load_or_create_keys(_KEYS_PATH)
        commitment = CommitmentMetadata(
            agent_id="psi_initiator",
            commitment_id="customers_v1",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.STRUCTURED,
            entry_count=1,
            field_count=3,
            estimated_size_mb=0.001,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.REAL_TIME,
            industry=Industry.FINANCE,
        )
        self._agent = PrivacyAgent(
            name="PSI Initiator (ADK)",
            description="Checks customers against partner sanction lists via PSI",
            card_url=card_url,
            host=host,
            port=port,
            role="ap3_initiator",
            operation=PSIOperation(),
            commitment=commitment,
            private_key=private_key,
            public_key=public_key,
        )
        async with self._agent.serving():
            self._started.set()
            await self._agent.wait()

    async def run_psi(self, *, peer_url: str, customer_row: str) -> str:
        if self._agent is None:
            raise RuntimeError("AP3 agent not initialized — call ensure_started() first")
        result = await self._agent.run_intent(peer_url=peer_url, inputs={"customer_data": customer_row})
        return str(result.result_data.metadata.get("description", ""))


def _get_runtime() -> _InitiatorRuntime:
    """Return process-level singleton — safe across module re-imports."""
    existing = sys.modules.get(_RUNTIME_KEY)
    if existing is not None:
        return existing  # type: ignore[return-value]
    rt = _InitiatorRuntime()
    sys.modules[_RUNTIME_KEY] = rt  # type: ignore[assignment]
    return rt


_runtime = _get_runtime()


async def run_psi_check(customer_row: str, peer_url: str | None = None) -> str:
    """Run PSI against the receiver and return a verdict.

    Args:
        customer_row: CSV row like "Name,ID,Address"
        peer_url: Receiver base URL (defaults to env PSI_RECEIVER_URL or localhost:10003)
    """
    receiver = peer_url or os.getenv("PSI_RECEIVER_URL", "http://localhost:10003")
    try:
        _runtime.ensure_started()
    except OSError:
        port = os.getenv("AP3_PORT", "10002")
        return (
            f"ERROR: AP3 server failed to bind port {port}. "
            f"Another process is likely using it. "
            f"Fix: `lsof -ti:{port} | xargs kill` or set a different AP3_PORT in .env."
        )
    except Exception as e:
        return f"ERROR: AP3 server failed to start. {type(e).__name__}: {e}"

    try:
        fut = _runtime.submit(_runtime.run_psi(peer_url=receiver, customer_row=customer_row))
        raw = await asyncio.wrap_future(fut)
        return _format_psi_result(raw, customer_row=customer_row, peer_url=receiver)
    except ConnectionRefusedError:
        return (
            f"ERROR: Could not reach the PSI receiver at {receiver}. "
            "Make sure the psi_receiver agent is running (Terminal 1: `uv run adk web`)."
        )
    except Exception as e:
        return f"ERROR: PSI check failed. {type(e).__name__}: {e}. Receiver: {receiver}."


def _create_model():
    """Build LLM from env vars. Default: Gemini 2.5 Flash.

    MODEL_PROVIDER  MODEL_NAME (default)            Required env key
    --------------- ------------------------------ ----------------------
    gemini          gemini-2.5-flash               GOOGLE_API_KEY
    claude          claude-sonnet-4-6              ANTHROPIC_API_KEY
    openai          gpt-4o                         OPENAI_API_KEY
    """
    provider = os.getenv("MODEL_PROVIDER", "gemini").lower()
    model_name = os.getenv("MODEL_NAME", "")

    if provider in ("gemini", "google"):
        from google.adk.models import Gemini
        return Gemini(model=model_name or "gemini-2.5-flash")

    # Non-Google providers via LiteLLM
    try:
        from google.adk.models.lite_llm import LiteLlm
    except ImportError as exc:
        raise ImportError(
            f"MODEL_PROVIDER={provider!r} requires LiteLLM. "
            "Install it: uv add 'google-adk[extensions]'"
        ) from exc

    if provider in ("claude", "anthropic"):
        return LiteLlm(model=f"anthropic/{model_name or 'claude-sonnet-4-6'}")
    if provider == "openai":
        return LiteLlm(model=f"openai/{model_name or 'gpt-4o'}")
    # Fallback: pass MODEL_NAME as-is to LiteLLM
    return LiteLlm(model=model_name or provider)


def _instruction() -> str:
    receiver = os.getenv("PSI_RECEIVER_URL", "http://localhost:10003")
    return f"""You run private set intersection (PSI) sanction checks via a cryptographic protocol.

When the user asks to check a customer:
- Call `run_psi_check` with a CSV row (Name,ID,Address).
- Interpret the tool result and respond in plain, friendly language:
  - Result contains `"is_match": true` → customer is on the sanction list.
  - Result contains `"is_match": false` → customer was not found.
  - Result starts with `ERROR:` → something went wrong. Explain the problem simply and tell the user what to do next. Do not repeat technical details like exception class names or shell commands verbatim — rephrase them in plain English.
  - Empty result → tell the user the check could not be completed and suggest they verify both agents are running.
- Never echo raw JSON or raw error strings — always translate into clear, helpful language.
- Always mention that the PSI protocol is privacy-preserving: neither side sees the other's raw data.

Default receiver: {receiver}

Examples:
- "Check Joe Quimby,S4928374,213 Church St"
- "Is Bob Johnson,C3456789,789 Pine Street sanctioned?"
"""


root_agent = LlmAgent(
    model=_create_model(),
    name="psi_initiator",
    description="PSI initiator agent (tool-calls AP3 PSI over A2A)",
    instruction=_instruction(),
    tools=[FunctionTool(run_psi_check)],
)
