"""ADK agent that also runs an AP3 PSI receiver (`ap3.a2a.PrivacyAgent`).

A process-level singleton (keyed in `sys.modules`) ensures the receiver
server starts only once even if ADK reimports this module for graph
previews or session creation.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.adk.agents import LlmAgent

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
_SANCTIONS_PATH = Path(__file__).parent / "data" / "sanctions.txt"
# Sentinel key — survives module re-imports inside the same process.
_SERVER_KEY = "__ap3_psi_receiver_server__"

_DEFAULT_SANCTIONS = [
    "Joe Quimby,S4928374,213 Church St",
    "C. Montgomery Burns,S9283746,1000 Mammon Lane",
    "Bob Johnson,C3456789,789 Pine Street",
]


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


def _load_sanctions(path: Path) -> list[str]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(_DEFAULT_SANCTIONS) + "\n")
        return list(_DEFAULT_SANCTIONS)
    entries = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    return entries if entries else list(_DEFAULT_SANCTIONS)


class _BackgroundServer:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = threading.Event()
        self._start_error: Optional[BaseException] = None

    def ensure_started(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._started.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="ap3-psi-receiver", daemon=True)
        self._thread.start()
        self._started.wait(timeout=10)
        if self._start_error:
            err = self._start_error
            if isinstance(err, SystemExit):
                # uvicorn calls sys.exit(1) on port-binding failure.
                # Re-raising SystemExit in the main thread kills the process.
                # Convert to OSError so callers can catch it normally.
                port = int(os.getenv("AP3_PORT", "10003"))
                raise OSError(
                    f"AP3 server could not start on port {port} (uvicorn exit {err.code}). "
                    f"Port may be in use. Free it: lsof -ti:{port} | xargs kill"
                )
            raise err

    def _run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._serve_forever())
        except SystemExit as e:
            # uvicorn raises SystemExit on port-binding failure.
            # Store it but do NOT re-raise — see ensure_started() note above.
            self._start_error = e
            self._started.set()
        except BaseException as e:
            self._start_error = e
            self._started.set()
            raise

    async def _serve_forever(self) -> None:
        port = int(os.getenv("AP3_PORT", "10003"))
        card_url = os.getenv("CARD_URL", f"http://localhost:{port}")
        host = os.getenv("HOST", "127.0.0.1")
        private_key, public_key = _load_or_create_keys(_KEYS_PATH)
        sanction_list = _load_sanctions(_SANCTIONS_PATH)
        commitment = CommitmentMetadata(
            agent_id="psi_receiver",
            commitment_id="sanctions_v1",
            data_structure=DataStructure.CUSTOMER_LIST,
            data_format=DataFormat.STRUCTURED,
            entry_count=len(sanction_list),
            field_count=3,
            estimated_size_mb=0.001,
            last_updated=datetime.now(timezone.utc).isoformat(),
            data_freshness=DataFreshness.REAL_TIME,
            industry=Industry.FINANCE,
        )
        agent = PrivacyAgent(
            name="PSI Receiver (ADK)",
            description="Holds a sanction list; performs PSI on request",
            card_url=card_url,
            host=host,
            port=port,
            role="ap3_receiver",
            operation=PSIOperation(),
            commitment=commitment,
            private_key=private_key,
            public_key=public_key,
            receiver_config_provider=lambda: {"sanction_list": sanction_list},
            # ADK example runs both sides on localhost.
            allow_private_initiator_urls=True,
        )
        async with agent.serving():
            self._started.set()
            await agent.wait()


def _get_server() -> _BackgroundServer:
    """Return process-level singleton — safe across module re-imports."""
    existing = sys.modules.get(_SERVER_KEY)
    if existing is not None:
        return existing  # type: ignore[return-value]
    srv = _BackgroundServer()
    sys.modules[_SERVER_KEY] = srv  # type: ignore[assignment]
    return srv


_server = _get_server()
try:
    _server.ensure_started()
except OSError as _e:
    port = os.getenv("AP3_PORT", "10003")
    raise RuntimeError(
        f"AP3 receiver server could not bind port {port}: {_e}. "
        f"Free it with `lsof -ti:{port} | xargs kill` or set a different AP3_PORT in your .env."
    ) from _e


def _create_model():
    """Build LLM from env vars. Default: Gemini 2.5 Flash.

    MODEL_PROVIDER  MODEL_NAME (default)            Required env key
    --------------- ------------------------------ ----------------------
    gemini          gemini-2.5-flash               GOOGLE_API_KEY
    claude          claude-sonnet-4-5-20251001      ANTHROPIC_API_KEY
    openai          gpt-4o                         OPENAI_API_KEY
    """
    provider = os.getenv("MODEL_PROVIDER", "gemini").lower()
    model_name = os.getenv("MODEL_NAME", "")

    if provider in ("gemini", "google"):
        from google.adk.models import Gemini
        return Gemini(model=model_name or "gemini-2.5-flash")

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
    return LiteLlm(model=model_name or provider)


def _instruction() -> str:
    return (
        "You are a PSI receiver. Your AP3/A2A server is already running and will respond "
        "to PSI protocol envelopes from the initiator. If asked, explain that you never "
        "reveal the sanction list — you only participate in the cryptographic protocol."
    )


root_agent = LlmAgent(
    model=_create_model(),
    name="psi_receiver",
    description="PSI receiver agent (starts AP3 A2A server on localhost:10003)",
    instruction=_instruction(),
    tools=[],
)
