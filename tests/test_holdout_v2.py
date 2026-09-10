import json

import pytest

from agent.openai_model import BudgetExceeded, OpenAIModel
from agent.orchestration import ModelConfig
from evals.holdout import ROOT, replay, run_case
from evals.holdout_v2 import RunAllowance


class FakeModel:
    requests = 0
    actual_usd = 0.0

    def respond(self, messages, config):
        self.requests += 1
        raise RuntimeError("delivery unknown")


def test_run_cap_rejects_before_dispatch_and_keeps_unknown_reservation():
    model = FakeModel()
    config = ModelConfig()
    reserve = OpenAIModel.reservation([], config)
    allowance = RunAllowance(model, budget=reserve, requests=2)
    with pytest.raises(RuntimeError, match="delivery unknown"):
        allowance.respond([], config)
    assert allowance.charged == reserve
    with pytest.raises(BudgetExceeded):
        allowance.respond([], config)
    assert model.requests == 1


def test_run_request_cap_does_not_reset_project_usage():
    model = FakeModel()
    model.requests = 63
    with pytest.raises(BudgetExceeded):
        RunAllowance(model).respond([], ModelConfig())
    assert model.requests == 63


def test_new_suite_mock_contracts_for_both_strategies(tmp_path):
    suite = json.loads((ROOT / "evals/holdout-v2.json").read_text(encoding="utf-8"))
    assert len(suite["cases"]) == 6
    assert sum(len(case["steps"]) for case in suite["cases"]) <= 9
    for case in suite["cases"]:
        for strategy in ("fixed", "agent"):
            result = run_case(tmp_path, case, strategy, replay(case, strategy))
            assert result["task_success"], (case["id"], strategy, result)
