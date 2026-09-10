import json

import httpx
import pytest

from agent.live_model import LiveModel
from agent.openai_model import BudgetExceeded
from agent.orchestration import ModelConfig


def test_evaluation_and_web_share_cap_but_report_separate_usage(tmp_path):
    def answer(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"tool":"finish","arguments":{"text":"ok"}}'},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
        )

    args = {
        "api_key": "fake",
        "authorized": True,
        "max_requests": 2,
        "transport": httpx.MockTransport(answer),
    }
    web = LiveModel(tmp_path, **args)
    evaluation = LiveModel(tmp_path, **args)
    web.respond([], ModelConfig())
    evaluation.respond([], ModelConfig())
    assert evaluation.requests == 1
    assert evaluation.input_tokens == 100
    assert evaluation.output_tokens == 10
    assert evaluation.actual_usd == pytest.approx(0.000032)
    assert evaluation.status()["requests"] == 2
    with pytest.raises(BudgetExceeded):
        evaluation.respond([], ModelConfig())
    assert len(evaluation.request_ids) == 1
    ledger = tmp_path / f"{evaluation.request_ids[0]}.jsonl"
    assert json.loads(ledger.read_text().splitlines()[0])["state"] == "reserved"
