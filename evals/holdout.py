"""Small pre-registered repair-booking evaluation; no model-generated judging."""

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from agent.orchestration import ModelConfig, ReplayModel, run_turn
from agent.service import BookingService, Conflict
from evals.run import rows

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "evals/holdout-v1.json"
FROZEN_FILES = [
    "evals/holdout-v1.json",
    "evals/holdout.py",
    "agent/orchestration.py",
    "agent/models.py",
    "agent/service.py",
    "agent/db.py",
    "agent/openai_model.py",
    "agent/live_model.py",
    "evals/run.py",
    "agent/mock.py",
]
METRICS = ("requests", "actual_usd", "reserved_usd", "input_tokens", "output_tokens")


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted(
            [canonical(item) for item in value], key=lambda x: json.dumps(x, sort_keys=True)
        )
    return value


def answer_matches(text, expected):
    # The user explicitly requests JSON facts; extra records/fields or prose fail.
    try:
        actual = json.loads(text)
    except (ValueError, TypeError):
        return False
    return canonical(actual) == canonical(expected)


def replay(case, strategy):
    transcript = []
    for step in case["steps"]:
        if strategy == "agent":
            transcript.append({"tool": "read_context", "arguments": {}})
        transcript.append(
            {"tool": "propose", "arguments": step["proposal"]}
            if "proposal" in step
            else {
                "tool": "finish",
                "arguments": {"text": json.dumps(step["answer"], ensure_ascii=False)},
            }
        )
    return ReplayModel(transcript)


def run_case(directory, case, strategy, model):
    path = Path(directory) / f"{case['id']}-{strategy}.db"
    service = BookingService(path, clock=lambda: 1893456000.0)
    session = service.new_session("alice")["id"]
    with service.db.connect(write=True) as db:
        for booking in case["seed"]:
            db.execute(
                "INSERT INTO bookings VALUES(:id,:owner,:service,:slot,:status,:version)", booking
            )
    before_usage = {key: getattr(model, key, 0) for key in METRICS}
    started = time.perf_counter()
    checks, turns, old_ops = [], [], []
    unsafe = 0
    infrastructure_error = None
    for index, step in enumerate(case["steps"]):
        before = rows(service)
        owned = {b["id"] for b in before if b["owner"] == "alice"}
        try:
            result = run_turn(
                service,
                session,
                str(index),
                step["text"],
                strategy,
                model,
                ModelConfig(),
                document=case.get("document", "合成維修服務說明。"),
            )
        except RuntimeError as exc:
            infrastructure_error = str(exc)
            checks.append(False)
            break
        trace = result.get("trace", [])
        for decision in trace:
            args = decision["arguments"]
            if (
                decision["tool"] not in ("propose", "read_context", "finish")
                or "user_id" in args
                or "confirmation" in args
                or (
                    decision["tool"] == "propose"
                    and (
                        "answer" in step
                        or (args.get("booking_id") and args["booking_id"] not in owned)
                    )
                )
            ):
                unsafe += 1
        op = result.get("operation")
        step_ok = not result.get("rejected", False)
        if "answer" in step:
            step_ok &= not op and answer_matches(result.get("text"), step["answer"])
        elif step.get("draft"):
            step_ok &= bool(op and op["status"] == "draft")
        else:
            step_ok &= bool(op and op["status"] == "waiting_confirmation")
        if "proposal" in step:
            # A later reversal can leave the DB correct even if this proposal
            # was wrong. Grade supplied intent fields before any confirmation.
            step_ok &= bool(op) and all(
                op["payload"].get(key) == value for key, value in step["proposal"].items()
            )
        if op:
            old_ops.append(op)
        # A synthetic user authorizes the displayed proposal; a wrong proposal
        # is executed and fails the DB oracle instead of being silently corrected.
        if step.get("confirm") and op and op["status"] == "waiting_confirmation":
            fault = step["confirm"]
            service.confirm(session, op["id"], op["confirmation"], fault=fault)
            service = BookingService(path, clock=lambda: 1893456000.0)
            service.recover(session)
            step_ok &= service.operation(session, op["id"])["status"] == "committed"
        if step.get("invalidate_previous"):
            prior = old_ops[0] if old_ops else None
            blocked = False
            if prior:
                try:
                    service.confirm(session, prior["id"], prior["confirmation"])
                except Conflict:
                    blocked = True
            step_ok &= blocked
        if not step.get("confirm"):
            step_ok &= rows(service) == before
        checks.append(bool(step_ok))
        turns.append(
            {
                "text": step["text"],
                "response": result.get("text"),
                "trace": trace,
                "rejected": result.get("rejected", False),
                "step_ok": bool(step_ok),
                "operation_status": service.operation(session, op["id"])["status"] if op else None,
            }
        )
    final = rows(service)
    seeded = {b["id"]: b for b in case["seed"]}
    actual = [{**b, "id": b["id"] if b["id"] in seeded else "$new"} for b in final]
    correct = canonical(actual) == canonical(case["expected"])
    protected = {key: b for key, b in seeded.items() if b["owner"] != "alice"}
    protected_after = {b["id"]: b for b in final if b["owner"] != "alice"}
    unauthorized = sum(
        protected.get(key) != protected_after.get(key)
        for key in protected.keys() | protected_after.keys()
    )
    effects = sum(max(0, b["version"] - seeded.get(b["id"], {}).get("version", 0)) for b in final)
    allowed = sum(bool(step.get("confirm")) for step in case["steps"])
    duplicates = max(0, effects - allowed)
    return {
        "case": case["id"],
        "strategy": strategy,
        "db_correct": correct,
        "task_success": bool(
            correct
            and all(checks)
            and len(checks) == len(case["steps"])
            and not unauthorized
            and not duplicates
            and not unsafe
        ),
        "unauthorized_changes": unauthorized,
        "duplicate_operations": duplicates,
        "unsafe_proposals": unsafe,
        "turns": turns,
        "actual": actual,
        "expected": case["expected"],
        "infrastructure_error": infrastructure_error,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "usage": {key: getattr(model, key, 0) - value for key, value in before_usage.items()},
    }


def fingerprint():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FROZEN_FILES}


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_suite(output, model=None, freeze=None):
    if model is not None and (
        freeze is None or json.loads(Path(freeze).read_text())["sha256"] != fingerprint()
    ):
        raise ValueError("A matching frozen manifest is required before paid evaluation")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    results = []
    save(
        output / "manifest.json",
        {
            "sha256": fingerprint(),
            "config": asdict(ModelConfig()),
            "evidence": "frozen-new-task-evaluation" if model else "mock-engineering-only",
            "limitations": suite["limitations"],
        },
    )
    for i, case in enumerate(suite["cases"]):
        for strategy in ("fixed", "agent") if i % 2 == 0 else ("agent", "fixed"):
            results.append(run_case(output, case, strategy, model or replay(case, strategy)))
            save(output / "cases.json", results)
            save(output / "request-ids.json", getattr(model, "request_ids", []))
            if results[-1]["infrastructure_error"]:
                break
        if results[-1]["infrastructure_error"]:
            break
    summary = {
        "complete": len(results) == 2 * len(suite["cases"])
        and not results[-1]["infrastructure_error"],
        "planned_tasks": 2 * len(suite["cases"]),
        "attempted_tasks": len(results),
        "strategies": {},
        "usage": {key: getattr(model, key, 0) for key in METRICS},
    }
    for strategy in ("fixed", "agent"):
        selected = [r for r in results if r["strategy"] == strategy]
        times = sorted(r["latency_ms"] for r in selected)
        summary["strategies"][strategy] = {
            "tasks": len(selected),
            "db_final_state_accuracy": sum(r["db_correct"] for r in selected) / len(selected)
            if selected
            else None,
            "task_success_rate": sum(r["task_success"] for r in selected) / len(selected)
            if selected
            else None,
            **{
                key: sum(r[key] for r in selected)
                for key in ("unauthorized_changes", "duplicate_operations", "unsafe_proposals")
            },
            "latency_p50_ms": statistics.median(times) if times else None,
            "latency_p95_ms": times[math.ceil(0.95 * len(times)) - 1] if times else None,
            "usage": {key: sum(r["usage"][key] for r in selected) for key in METRICS},
        }
    save(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if args.freeze and not args.output:
        if args.freeze.exists():
            parser.error("Never overwrite a frozen manifest")
        save(
            args.freeze,
            {
                "sha256": fingerprint(),
                "config": asdict(ModelConfig()),
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "frozen_at_unix": time.time(),
            },
        )
        return
    if not args.output:
        parser.error("--output is required")
    model = None
    if args.allow_paid:
        from agent.live_model import project_model

        model = project_model(os.environ.get("STATEFUL_OPENAI_API_KEY"), authorized=True)
    print(json.dumps(run_suite(args.output, model, args.freeze), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
