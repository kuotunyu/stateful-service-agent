from agent.orchestration import ReplayModel
from evals.cases import CASES
from evals.run import run_case


def test_wrong_model_proposal_is_a_failed_task_not_a_successful_tool_call(tmp_path):
    wrong = ReplayModel(
        [
            {
                "tool": "propose",
                "arguments": {
                    "action": "create",
                    "service": "洗衣機維修",
                    "slot": "2030-01-08T14:00:00+08:00",
                },
            }
        ]
    )
    result = run_case(tmp_path, CASES[0], "fixed", model=wrong)
    assert result["db_correct"] is False
    assert result["task_success"] is False


def test_claiming_completion_without_action_does_not_pass_missing_data_case(tmp_path):
    model = ReplayModel([{"tool": "finish", "arguments": {"text": "預約已完成！"}}])
    case = next(c for c in CASES if c["id"] == "missing_time")
    result = run_case(tmp_path, case, "fixed", model=model)
    assert result["db_correct"] is True
    assert result["task_success"] is False
