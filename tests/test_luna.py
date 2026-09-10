import json

import httpx
import pytest

from agent.openai_model import OpenAIModel
from agent.orchestration import ModelConfig


def test_luna_default_preserves_nonreasoning_contract_and_accounts_cache_writes(tmp_path):
    def answer(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-luna"
        assert body["reasoning_effort"] == "none"
        assert body["temperature"] == 0
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "model": "gpt-5.6-luna",
                "id": "test-luna",
                "service_tier": "default",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"tool":"finish","arguments":{"text":"ok"}}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 600, "cache_write_tokens": 200},
                },
            },
        )

    model = OpenAIModel(
        "fake", tmp_path / "usage.jsonl", authorized=True, transport=httpx.MockTransport(answer)
    )
    assert model.respond([], ModelConfig())["arguments"]["text"] == "ok"
    assert model.actual_usd == pytest.approx(0.000126)
    ledger = [json.loads(line) for line in model.ledger.read_text().splitlines()]
    assert ledger[0]["model"] == "gpt-5.6-luna"
    assert ledger[1]["response_model"] == "gpt-5.6-luna"


def test_luna_reservation_covers_cache_write_premium_and_rejects_long_context():
    messages = [{"role": "user", "content": "test"}]
    ceiling = len(json.dumps(messages, ensure_ascii=False).encode()) + 2048
    assert OpenAIModel.reservation(messages, ModelConfig()) == pytest.approx(
        ceiling * 0.25 / 1e6 + 500 * 1.20 / 1e6
    )
    with pytest.raises(ValueError, match="context"):
        OpenAIModel.reservation([{"role": "user", "content": "a" * 272001}], ModelConfig())
