"""Run the second small Luna evaluation using the existing DB oracle."""

import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from agent.openai_model import BudgetExceeded, OpenAIModel
from agent.orchestration import ModelConfig
from evals import holdout


class RunAllowance:
    """Bound this run while retaining the underlying durable project allowance."""

    def __init__(self, model, budget=0.05, requests=63):
        self.model = model
        self.budget = budget
        self.limit = requests
        self.charged = 0.0

    def __getattr__(self, name):
        return getattr(self.model, name)

    def respond(self, messages, config):
        reserve = OpenAIModel.reservation(messages, config)
        if self.requests >= self.limit or self.charged + reserve > self.budget:
            raise BudgetExceeded("Evaluation run allowance reached; no request sent")
        before_requests, before_actual = self.requests, self.actual_usd
        try:
            return self.model.respond(messages, config)
        finally:
            if self.requests > before_requests:
                # Unknown delivery retains its reservation; the runner stops on
                # infrastructure failure and never automatically retries it.
                self.charged += self.actual_usd - before_actual or reserve


def configure():
    holdout.SUITE = holdout.ROOT / "evals/holdout-v2.json"
    holdout.FROZEN_FILES = [
        name for name in holdout.FROZEN_FILES if name != "evals/holdout-v1.json"
    ] + [
        "evals/holdout-v2.json",
        "evals/holdout_v2.py",
        "agent/app.py",
        "docs/evaluations/luna-holdout-02/protocol.md",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    configure()
    if args.freeze and not args.output:
        if args.freeze.exists():
            parser.error("Never overwrite a frozen manifest")
        args.freeze.parent.mkdir(parents=True, exist_ok=True)
        holdout.save(
            args.freeze,
            {
                "sha256": holdout.fingerprint(),
                "config": asdict(ModelConfig()),
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=holdout.ROOT, text=True
                ).strip(),
                "frozen_at_unix": time.time(),
                "run_budget_usd": 0.05,
                "run_request_limit": 63,
            },
        )
        return
    if not args.output:
        parser.error("--output is required")
    model = None
    if args.allow_paid:
        from agent.live_model import project_model

        model = RunAllowance(
            project_model(os.environ.get("STATEFUL_OPENAI_API_KEY"), authorized=True)
        )
    print(
        json.dumps(holdout.run_suite(args.output, model, args.freeze), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
