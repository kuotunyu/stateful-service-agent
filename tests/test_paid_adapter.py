import json

import httpx
import pytest

from agent.openai_model import BudgetExceeded, OpenAIModel
from agent.orchestration import ModelConfig


def test_paid_access_requires_explicit_authorization_before_any_request(tmp_path):
    with pytest.raises(PermissionError):
        OpenAIModel("fake-test-key", tmp_path / "ledger.jsonl", authorized=False)
    assert not (tmp_path / "ledger.jsonl").exists()


def test_budget_reserves_unknown_requests_and_stops_at_request_limit(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("lost reply")

    model = OpenAIModel(
        "fake-test-key",
        tmp_path / "ledger.jsonl",
        authorized=True,
        max_requests=1,
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(RuntimeError, match="unknown"):
        model.respond([{"role": "user", "content": "hello"}], ModelConfig())
    with pytest.raises(BudgetExceeded):
        model.respond([{"role": "user", "content": "hello"}], ModelConfig())
    assert model.reserved_usd > 0
    assert model.requests == 1
    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert records[0]["state"] == "reserved"
    assert "fake-test-key" not in (tmp_path / "ledger.jsonl").read_text()


def test_adapter_validates_response_and_records_usage_without_secrets(tmp_path):
    def answer(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1-mini-2025-04-14"
        assert body["store"] is False
        assert body["max_completion_tokens"] == 500
        return httpx.Response(
            200,
            json={
                "id": "fake-response",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"tool":"finish","arguments":{"text":"查詢完成"}}'},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    model = OpenAIModel(
        "fake-test-key",
        tmp_path / "ledger.jsonl",
        authorized=True,
        transport=httpx.MockTransport(answer),
    )
    result = model.respond(
        [{"role": "user", "content": "查詢"}], ModelConfig(model="gpt-4.1-mini-2025-04-14")
    )
    assert result["arguments"]["text"] == "查詢完成"
    assert model.actual_usd == pytest.approx(0.000072)


def test_cost_limit_blocks_before_external_call(tmp_path):
    def should_not_run(request):
        pytest.fail("budget allowed an external request")

    model = OpenAIModel(
        "fake-test-key",
        tmp_path / "ledger.jsonl",
        authorized=True,
        budget_usd=0.000001,
        transport=httpx.MockTransport(should_not_run),
    )
    with pytest.raises(BudgetExceeded):
        model.respond([{"role": "user", "content": "查詢"}], ModelConfig())


def test_http_rejection_reports_status_without_echoing_provider_body(tmp_path):
    model = OpenAIModel(
        "fake-test-key",
        tmp_path / "ledger.jsonl",
        authorized=True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401, json={"error": {"message": "Invalid API key: fake-test-key"}}
            )
        ),
    )
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        model.respond([{"role": "user", "content": "查詢"}], ModelConfig())
    assert "fake-test-key" not in str(error.value)
    assert "fake-test-key" not in model.ledger.read_text()


def test_cached_input_uses_cached_rate_in_reported_cost(tmp_path):
    model = OpenAIModel(
        "fake-test-key",
        tmp_path / "ledger.jsonl",
        authorized=True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"tool":"finish","arguments":{"text":"查詢"}}'},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 20,
                        "prompt_tokens_details": {"cached_tokens": 800},
                    },
                },
            )
        ),
    )
    model.respond(
        [{"role": "user", "content": "查詢"}], ModelConfig(model="gpt-4.1-mini-2025-04-14")
    )
    assert model.actual_usd == pytest.approx(0.000192)
