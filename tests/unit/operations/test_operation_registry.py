"""Unit tests for Operation session lifecycle (sessions live inside Operation)."""

import pytest

from ap3 import Operation, OperationResult


class ThresholdOp(Operation):
    operation_id = "test.threshold.v1"

    def on_start(self, role, inputs, config, context):
        del config, context
        if role != "initiator":
            raise ValueError("start only for initiator")
        value = int(inputs["value"])
        return OperationResult(next_state={"value": value}, outgoing={"value": value})

    def on_process(self, role, state, message, config, context):
        del context
        if role == "receiver":
            threshold = int(config["threshold"])
            approved = int(message["value"]) >= threshold
            return OperationResult(done=True, outgoing={"approved": approved})
        return OperationResult(
            next_state=state,
            done=True,
            result={"approved": bool(message["approved"]), "value": int(state["value"])},
        )


class ContextAwareOp(Operation):
    operation_id = "test.context.v1"

    def on_start(self, role, inputs, config, context):
        del role, inputs, config, context
        return OperationResult(next_state={"count": 0}, outgoing={"step": 1})

    def on_process(self, role, state, message, config, context):
        del role, config
        if context["is_first_message"]:
            assert state == {}
            return OperationResult(next_state={"count": 1}, outgoing={"step": 2})
        assert state["count"] == 1
        assert message["step"] == 2
        return OperationResult(done=True, result={"ok": True})



class TestOperationSessionLifecycle:
    @pytest.mark.unit
    def test_two_party_message_flow(self):
        initiator = ThresholdOp()
        receiver = ThresholdOp()

        init_step = initiator.start(role="initiator", inputs={"value": 81})
        recv_step = receiver.receive(
            role="receiver",
            message=init_step["outgoing"],
            config={"threshold": 80},
        )
        final = initiator.process(init_step["session_id"], recv_step["outgoing"])

        assert final["done"] is True
        assert final["result"] == {"approved": True, "value": 81}

    @pytest.mark.unit
    def test_receive_and_process_context_flags(self):
        initiator = ContextAwareOp()
        receiver = ContextAwareOp()

        first = initiator.start(role="initiator", inputs={"unused": True})
        recv = receiver.receive(role="receiver", message=first["outgoing"])
        final = receiver.process(recv["session_id"], recv["outgoing"])

        assert final["done"] is True
        assert final["result"] == {"ok": True}

    @pytest.mark.unit
    def test_has_session_tracks_active_sessions(self):
        op = ThresholdOp()
        result = op.start(role="initiator", inputs={"value": 50})
        sid = result["session_id"]

        assert op.has_session(sid) is True

        # Complete the session
        r2 = ThresholdOp()
        recv = r2.receive(role="receiver", message=result["outgoing"], config={"threshold": 40})
        op.process(sid, recv["outgoing"])

        assert op.has_session(sid) is False

    @pytest.mark.unit
    def test_explicit_session_id(self):
        op = ThresholdOp()
        result = op.start(role="initiator", inputs={"value": 10}, session_id="my-sid")
        assert result["session_id"] == "my-sid"
        assert op.has_session("my-sid") is True


    def test_process_raises_for_unknown_session(self):
        op = ThresholdOp()
        with pytest.raises(KeyError, match="Unknown session"):
            op.process("nonexistent-session", {"value": 5})

    @pytest.mark.unit
    def test_concrete_operation_requires_non_empty_operation_id(self):
        with pytest.raises(TypeError, match="must define a non-empty 'operation_id'"):
            class MissingOperationIdOp(Operation):
                def on_start(self, role, inputs, config, context):
                    del role, inputs, config, context
                    return OperationResult()

                def on_process(self, role, state, message, config, context):
                    del role, state, message, config, context
                    return OperationResult()

    @pytest.mark.unit
    def test_independent_instances_have_isolated_sessions(self):
        """Two Operation instances do not share session state."""
        op1 = ThresholdOp()
        op2 = ThresholdOp()

        r1 = op1.start(role="initiator", inputs={"value": 10})
        assert op1.has_session(r1["session_id"]) is True
        assert op2.has_session(r1["session_id"]) is False
