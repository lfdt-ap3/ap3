"""PSI Sanction-Check operation built on ap3.Operation.

Wire flow (4 envelopes, OB = initiator, BB = receiver):

    OB → BB : phase="init"  payload = commit(sid_0, blind)   [OB commits sid_0, hidden]
    BB → OB : phase="msg0"  payload = sid_1                  [BB reveals sid_1]
    OB → BB : phase="msg1"  payload = sid_0 || blind || psc_msg1   [OB opens the commit]
    BB → OB : phase="msg2"  payload = psc_msg2

session_id = SHA256(SESSION_ID_LABEL || sid_0 || sid_1). 

OB commits to sid_0 first, BB then reveals sid_1, and OB finally opens the commit in msg1. 

Because sid_0 is bound by the commit before
OB sees sid_1, OB cannot grind session_id; because BB doesn't see sid_0 until
after picking sid_1, BB cannot grind either. session_id is freshly contributory.
"""

from __future__ import annotations

import base64
import logging
import secrets
from typing import Any, Dict

from ap3 import Operation, OperationResult
from ap3_functions.exceptions import ProtocolError
from ap3_functions.psi import ffi as psi_ffi, HASH_SIZE, create_commitment, verify_commitment
from ap3_functions.psi.ffi import SESSION_ID_SIZE

logger = logging.getLogger(__name__)


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")


def _b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("utf-8"))


class PSIOperation(Operation):
    """PSI Sanction Check protocol with contributory session_id.

    `PSI` flow: OB commits sid_0 in `init`, BB reveals sid_1 in `msg0`, OB
    opens the commit (sid_0, blind) alongside psc_msg1 in `msg1`. Both parties
    derive session_id = H(label, sid_0, sid_1) independently.
    """

    operation_type = "PSI"
    operation_id = "protocol.psi.sanction.v1"

    # -- initiator (OB) entry point ----------------------------------------

    def on_start(
        self,
        role: str,
        inputs: Any,
        config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> OperationResult:
        del context, config
        if role != "initiator":
            raise ProtocolError("PSI start is only supported for role='initiator'")
        customer_data = inputs.get("customer_data") if isinstance(inputs, dict) else inputs
        if not customer_data:
            raise ProtocolError("PSI requires customer_data")

        sid_0 = secrets.token_bytes(SESSION_ID_SIZE)
        blind_value = secrets.token_bytes(HASH_SIZE)
        commit = create_commitment(sid_0, blind_value)

        # Open the session with a wire-level kick-off. No sid commitment
        # yet — BB commits sid_1 first in its reply.
        return OperationResult(
            next_state={
                "customer_data": str(customer_data),
                "sid_0": _b64e(sid_0),
                "blind_value": _b64e(blind_value),
            },
            outgoing={"phase": "init", "message": _b64e(commit)},
            metadata={"protocol": "psi"},
        )

    # -- shared on_process dispatcher --------------------------------------

    def on_process(
        self,
        role: str,
        state: Dict[str, Any],
        message: Dict[str, Any],
        config: Dict[str, Any],
        context: Dict[str, Any],
    ) -> OperationResult:
        del context
        if role == "receiver":
            return self._receiver_step(state, message, config)
        if role == "initiator":
            return self._initiator_step(state, message)
        raise ProtocolError(f"PSI: unknown role {role!r}")

    # -- receiver (BB) -----------------------------------------------------

    def _receiver_step(
        self,
        state: Dict[str, Any],
        message: Dict[str, Any],
        config: Dict[str, Any],
    ) -> OperationResult:
        phase = message.get("phase")

        if phase == "init":
            commit = _b64d(message["message"])
            if len(commit) != HASH_SIZE:
                raise ProtocolError("PSI Invalid commitment", round_num=0)

            sanction_list = config.get("sanction_list") or []
            if not sanction_list:
                raise ProtocolError(
                    "sanction_list must be non-empty", round_num=0
                )
            sid_1 = secrets.token_bytes(SESSION_ID_SIZE)
            sanction_hashes = [
                psi_ffi.generate_hash(row, "Customer") for row in sanction_list
            ]
            return OperationResult(
                next_state={
                    "commit": _b64e(commit),
                    "sid_1": _b64e(sid_1),
                    "sanction_hashes": [_b64e(h) for h in sanction_hashes],
                },
                outgoing={"phase": "msg0", "message": _b64e(sid_1)},
                metadata={"protocol": "psi"},
            )

        if phase == "msg1":
            commit_b64 = state.get("commit")
            sid_1_b64 = state.get("sid_1")
            sanction_hashes_b64 = state.get("sanction_hashes")
            if not commit_b64 or not sid_1_b64 or sanction_hashes_b64 is None:
                raise ProtocolError("PSI receiver state is missing", round_num=1)

            payload = _b64d(message["message"])
            if len(payload) < SESSION_ID_SIZE + HASH_SIZE:
                raise ProtocolError("PSI msg1 payload too short for sid_0 and blind_value", round_num=1)
            sid_0 = payload[:SESSION_ID_SIZE]
            blind_value = payload[SESSION_ID_SIZE:SESSION_ID_SIZE+HASH_SIZE]
            psc_msg1_bytes = payload[SESSION_ID_SIZE+HASH_SIZE:]

            if not verify_commitment(_b64d(commit_b64), sid_0, blind_value):
                raise ProtocolError("PSI Invalid commitment", round_num=1)

            session_id = psi_ffi.compute_session_id(sid_0, _b64d(sid_1_b64))
            sanction_hashes = [_b64d(h) for h in sanction_hashes_b64]
            psc_msg2 = psi_ffi.process_psc_msg1(
                session_id, psc_msg1_bytes, sanction_hashes
            )
            return OperationResult(
                done=True,
                outgoing={"phase": "msg2", "message": _b64e(psc_msg2)},
                metadata={"protocol": "psi"},
            )

        raise ProtocolError(f"PSI receiver: unexpected phase {phase!r}")

    # -- initiator (OB) ----------------------------------------------------

    def _initiator_step(
        self, state: Dict[str, Any], message: Dict[str, Any]
    ) -> OperationResult:
        phase = message.get("phase")

        if phase == "msg0":
            customer_data = state.get("customer_data")
            if not customer_data:
                raise ProtocolError(
                    "PSI initiator state is missing customer_data", round_num=0
                )
            sid_1 = _b64d(message["message"])
            if len(sid_1) != SESSION_ID_SIZE:
                raise ProtocolError(
                    f"PSI msg0: sid_1 must be {SESSION_ID_SIZE} bytes", round_num=0
                )

            sid_0_b64 = state.get("sid_0")
            blind_value_b64 = state.get("blind_value")
            if not sid_0_b64 or blind_value_b64 is None:
                raise ProtocolError("PSI initiator state is missing", round_num=0)

            sid_0 = _b64d(sid_0_b64)
            blind_value = _b64d(blind_value_b64)

            session_id = psi_ffi.compute_session_id(sid_0, sid_1)
            customer_hash = psi_ffi.generate_hash(customer_data, "Customer")
            psc_state, psc_msg1 = psi_ffi.create_psc_msg1(session_id, customer_hash)
            return OperationResult(
                next_state={"initiator_state": _b64e(psc_state)},
                outgoing={"phase": "msg1", "message": _b64e(sid_0 + blind_value + psc_msg1)},
                metadata={"protocol": "psi"},
            )

        if phase == "msg2":
            initiator_state = state.get("initiator_state")
            if not initiator_state:
                raise ProtocolError("PSI initiator state is missing", round_num=2)
            is_match = psi_ffi.process_psc_msg2(
                _b64d(initiator_state), _b64d(message["message"])
            )
            return OperationResult(
                done=True,
                result={"is_match": bool(is_match)},
                metadata={"protocol": "psi"},
            )

        raise ProtocolError(f"PSI initiator: unexpected phase {phase!r}")
