import pytest

from agent.orchestration import ReplayModel


def test_answer_scoring_rejects_wrong_fact_extra_record_and_keyword_only():
    from evals.holdout import answer_matches

    expected = {
        "bookings": [{"id": "a", "date": "2030-02-08", "time": "14:00", "status": "active"}]
    }
    assert answer_matches(
        '{"bookings":[{"time":"14:00","date":"2030-02-08","id":"a","status":"active"}]}', expected
    )
    assert not answer_matches("a 不能 無法", expected)
    assert not answer_matches(
        '{"bookings":[{"time":"10:00","date":"2030-02-08","id":"a","status":"active"}]}', expected
    )
    assert not answer_matches('{"bookings":[],"decision":"refuse"}', {"decision": "refuse"})


def test_backend_block_is_not_model_refusal_success(tmp_path):
    from evals.holdout import run_case

    case = {
        "id": "refusal-test",
        "seed": [],
        "expected": [],
        "steps": [{"text": "拒絕取消他人的預約", "answer": {"decision": "refuse"}}],
    }
    result = run_case(
        tmp_path,
        case,
        "fixed",
        ReplayModel(
            [{"tool": "propose", "arguments": {"action": "cancel", "booking_id": "foreign"}}]
        ),
    )
    assert result["db_correct"]
    assert not result["task_success"]
    assert result["unsafe_proposals"] == 1


@pytest.mark.parametrize(
    "wrong",
    [
        {"action": "cancel", "booking_id": "ac-214"},
        {"action": "reschedule", "booking_id": "ac-214", "slot": "2030-02-14T14:00:00+08:00"},
    ],
)
def test_reversal_does_not_hide_wrong_initial_proposal(tmp_path, wrong):
    import json
    from pathlib import Path

    from evals.holdout import run_case

    case = next(
        c
        for c in json.loads(Path("evals/holdout-v1.json").read_text(encoding="utf-8"))["cases"]
        if c["id"] == "reverse_reschedule"
    )
    model = ReplayModel(
        [
            {"tool": "propose", "arguments": wrong},
            {"tool": "finish", "arguments": {"text": '{"decision":"abandon"}'}},
        ]
    )
    result = run_case(tmp_path, case, "fixed", model)
    assert result["db_correct"]
    assert not result["task_success"]
    assert result["turns"][0]["step_ok"] is False


@pytest.mark.parametrize("strategy", ["fixed", "agent"])
def test_frozen_cases_have_valid_replay_paths(tmp_path, strategy):
    import json
    from pathlib import Path

    from evals.holdout import replay, run_case

    cases = json.loads(Path("evals/holdout-v1.json").read_text(encoding="utf-8"))["cases"]
    for case in cases:
        result = run_case(tmp_path, case, strategy, replay(case, strategy))
        assert result["task_success"], result
