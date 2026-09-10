import json
from pathlib import Path

import httpx
import pytest

from agent.openai_model import OpenAIModel
from agent.orchestration import ModelConfig, ReplayModel, run_turn
from agent.service import BookingService


def create_booking(service, session):
    turn = service.begin_turn(session, "seed", "seed")
    op = service.propose(
        session,
        turn["revision"],
        {
            "action": "create",
            "service": "冷氣維修",
            "slot": "2041-07-23T10:00:00+08:00",
        },
    )
    return service.confirm(session, op["id"], op["confirmation"])["receipt"]["booking"]


@pytest.mark.parametrize("strategy", ["fixed", "agent"])
def test_model_cannot_rebase_a_stale_read_onto_new_booking_version(tmp_path, strategy):
    service = BookingService(tmp_path / "race.db")
    a, b = (service.new_session("alice")["id"] for _ in range(2))
    booking = create_booking(service, a)

    class RacingModel:
        read = False

        def respond(self, messages, config):
            if strategy == "agent" and not self.read:
                self.read = True
                return {"tool": "read_context", "arguments": {}}
            turn = service.begin_turn(b, "race", "reschedule elsewhere")
            op = service.propose(
                b,
                turn["revision"],
                {
                    "action": "reschedule",
                    "booking_id": booking["id"],
                    "slot": "2041-07-24T16:00:00+08:00",
                },
            )
            service.confirm(b, op["id"], op["confirmation"])
            return {
                "tool": "propose",
                "arguments": {
                    "action": "reschedule",
                    "booking_id": booking["id"],
                    "slot": "2041-07-23T14:00:00+08:00",
                },
            }

    result = run_turn(service, a, "move", "next slot", strategy, RacingModel(), ModelConfig())
    assert result.get("rejected") is True
    assert "operation" not in result
    current = service.snapshot(a)["bookings"][0]
    assert (current["version"], current["slot"]) == (2, "2041-07-24T16:00:00+08:00")


@pytest.mark.parametrize("strategy", ["fixed", "agent"])
@pytest.mark.parametrize(
    "dialogue",
    json.loads(
        (Path(__file__).parent / "fixtures/review-dialogues.json").read_text(encoding="utf-8")
    ),
    ids=lambda case: case["id"],
)
def test_clarification_context_survives_restart_without_exposing_confirmation(
    tmp_path, strategy, dialogue
):
    path = tmp_path / "history.db"
    service = BookingService(path)
    session = service.new_session("alice")["id"]
    first, question = dialogue["request"], dialogue["question"]
    run_turn(
        service,
        session,
        "one",
        first,
        strategy,
        ReplayModel([{"tool": "finish", "arguments": {"text": question}}]),
        ModelConfig(),
    )

    class ContextModel:
        def respond(self, messages, config):
            prompt = json.dumps(messages, ensure_ascii=False)
            assert first in prompt and question in prompt
            assert service.session(session)["csrf"] not in prompt
            return {
                "tool": "propose",
                "arguments": dialogue["proposal"],
            }

    result = run_turn(
        BookingService(path),
        session,
        "two",
        dialogue["followup"],
        strategy,
        ContextModel(),
        ModelConfig(),
    )
    assert result["operation"]["payload"]["slot"] == dialogue["slot"]
    assert service.snapshot(session)["bookings"] == []


@pytest.mark.parametrize("fields", [{"date": "2041-07-24"}, {"time": "14:00"}])
def test_contradictory_time_fields_are_rejected_without_creating_operation(tmp_path, fields):
    service = BookingService(tmp_path / "conflict.db")
    session = service.new_session("alice")["id"]
    turn = service.begin_turn(session, "one", "new date")
    with pytest.raises(ValueError):
        service.propose(
            session,
            turn["revision"],
            {
                "action": "create",
                "service": "冷氣維修",
                "slot": "2041-07-23T10:00:00+08:00",
                **fields,
            },
        )
    assert service.snapshot(session)["operations"] == []


def test_model_completion_claim_has_durable_authoritative_no_submission_status(tmp_path):
    service = BookingService(tmp_path / "claim.db")
    session = service.new_session("alice")["id"]
    result = run_turn(
        service,
        session,
        "claim",
        "book repair",
        "fixed",
        ReplayModel([{"tool": "finish", "arguments": {"text": "Booking completed!"}}]),
        ModelConfig(),
        live=True,
    )
    assert result.get("response_kind") == "model_text"
    assert result["verification"]["status"] == "no_submission"
    assert service.snapshot(session)["bookings"] == []
    assert BookingService(service.path).snapshot(session)["messages"][-1]["response"] == result


def test_adapter_invalid_decision_retains_forbidden_tool_for_audit(tmp_path):
    def answer(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "tool": "confirm",
                                    "arguments": {},
                                    "confirmation": "forged",
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )

    model = OpenAIModel(
        "fake", tmp_path / "usage.jsonl", authorized=True, transport=httpx.MockTransport(answer)
    )
    service = BookingService(tmp_path / "adapter.db")
    session = service.new_session("alice")["id"]
    result = run_turn(service, session, "one", "query", "fixed", model, ModelConfig())
    assert result["rejected"]
    assert result["trace"] and result["trace"][0]["tool"] == "confirm"
    assert result["trace"][0]["rejected"] == "invalid_schema"
    assert "forged" not in result["text"]


def test_invalid_proposal_does_not_expose_raw_argument_dump_or_reuse_it_as_history(tmp_path):
    service = BookingService(tmp_path / "schema.db")
    session = service.new_session("alice")["id"]
    result = run_turn(
        service,
        session,
        "bad",
        "book repair",
        "fixed",
        ReplayModel(
            [
                {
                    "tool": "propose",
                    "arguments": {
                        "action": "create",
                        "service": "invalid",
                        "confirmation": "private-audit-marker",
                    },
                }
            ]
        ),
        ModelConfig(),
    )
    assert result["rejected"]
    assert "private-audit-marker" not in result["text"]
    assert "input_value" not in result["text"]
    history = service.conversation(session, 2)
    assert "private-audit-marker" not in json.dumps(history)
