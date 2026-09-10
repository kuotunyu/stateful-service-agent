"""Optional paid evaluation adapter. Never constructed by the default web app."""

import json
import os
import time
from pathlib import Path

import httpx

from agent.orchestration import Decision


class BudgetExceeded(RuntimeError):
    pass


class OpenAIModel:
    # Official standard text rates checked 2026-09-10, USD per token.
    INPUT_RATE = 0.40 / 1_000_000
    CACHED_INPUT_RATE = 0.10 / 1_000_000
    OUTPUT_RATE = 1.60 / 1_000_000

    def __init__(
        self, api_key, ledger, *, authorized=False, budget_usd=1.0, max_requests=144, transport=None
    ):
        if not authorized:
            raise PermissionError("Explicit paid evaluation authorization is required")
        if not api_key:
            raise ValueError(
                "Set the dedicated STATEFUL_OPENAI_API_KEY; do not reuse other projects' files"
            )
        if not (0 < budget_usd <= 1 and 0 < max_requests <= 144):
            raise ValueError("This pilot is limited to USD 1 and 144 requests")
        self.api_key = api_key
        self.ledger = Path(ledger)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to reset the budget of an existing run.
        self.ledger.touch(exist_ok=False)
        self.budget_usd, self.max_requests = budget_usd, max_requests
        self.requests = 0
        self.reserved_usd = self.actual_usd = 0.0
        self.input_tokens = self.output_tokens = 0
        self.transport = transport

    def _record(self, data):
        with self.ledger.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"time": time.time(), **data}, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())

    @classmethod
    def reservation(cls, messages, config):
        if config.model != "gpt-4.1-mini-2025-04-14" or config.max_output_tokens > 500:
            raise ValueError(
                "Pilot pricing is only approved for the configured snapshot and output cap"
            )
        # For text-only messages, UTF-8 byte count plus generous message overhead
        # conservatively reserves token cost before dispatch. Unknown replies keep
        # their full reservation; there is no automatic transport retry.
        input_ceiling = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 2048
        return input_ceiling * cls.INPUT_RATE + config.max_output_tokens * cls.OUTPUT_RATE

    def respond(self, messages, config):
        reserve = self.reservation(messages, config)
        if self.requests >= self.max_requests or self.reserved_usd + reserve > self.budget_usd:
            raise BudgetExceeded("Paid evaluation request or cost cap reached")
        self.requests += 1
        self.reserved_usd += reserve
        self._record(
            {
                "request": self.requests,
                "state": "reserved",
                "reserved_usd": reserve,
                "cumulative_reserved_usd": self.reserved_usd,
            }
        )
        try:
            with httpx.Client(transport=self.transport, timeout=30, trust_env=False) as client:
                response = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": config.model,
                        "messages": messages,
                        "temperature": config.temperature,
                        "max_completion_tokens": config.max_output_tokens,
                        "response_format": {"type": "json_object"},
                        "store": False,
                        "service_tier": "default",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            self._record({"request": self.requests, "state": "http_error", "status": status})
            raise RuntimeError(
                f"Model API returned HTTP {status}; pilot stopped, reservation retained"
            ) from None
        except (httpx.HTTPError, ValueError):
            self._record({"request": self.requests, "state": "unknown"})
            raise RuntimeError(
                "Model transport failed; billing is unknown and reservation is retained"
            ) from None
        usage = data.get("usage", {})
        if "prompt_tokens" in usage and "completion_tokens" in usage:
            self.input_tokens += usage["prompt_tokens"]
            self.output_tokens += usage["completion_tokens"]
            cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            cost = (
                (usage["prompt_tokens"] - cached) * self.INPUT_RATE
                + cached * self.CACHED_INPUT_RATE
                + usage["completion_tokens"] * self.OUTPUT_RATE
            )
            self.actual_usd += cost
            self._record(
                {
                    "request": self.requests,
                    "state": "response",
                    "usage": usage,
                    "actual_usd": cost,
                    "response_id": data.get("id"),
                }
            )
            if cost > reserve:
                raise BudgetExceeded("Provider usage exceeded conservative reservation; stopped")
        else:
            self._record({"request": self.requests, "state": "usage_unknown"})
        try:
            choice = data["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("Model output incomplete or refused")
            return Decision.model_validate_json(choice["message"]["content"]).model_dump()
        except (KeyError, IndexError, TypeError):
            raise ValueError("Model returned no usable structured decision") from None
