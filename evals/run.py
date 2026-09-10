"""Run: uv run python -m evals.run --output artifacts/mock-eval"""

import argparse
import json
import os
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from agent.orchestration import ModelConfig, ReplayModel, run_turn
from agent.service import BookingService, Conflict
from evals.cases import CASES


def replay_for(case, strategy):
    final = (
        {"tool": "propose", "arguments": case["proposal"]}
        if "proposal" in case
        else {"tool": "finish", "arguments": {"text": case["finish"]}}
    )
    return ReplayModel(
        ([{"tool": "read_context", "arguments": {}}] if strategy == "agent" else []) + [final]
    )


def rows(service):
    with service.db.connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM bookings ORDER BY owner,slot,id")]


def project(bookings):
    return sorted(
        [
            {key: b[key] for key in ("owner", "service", "slot", "status", "version")}
            for b in bookings
        ],
        key=lambda b: (b["slot"], b["service"]),
    )


def run_case(directory, case, strategy, model=None, config=None):
    config = config or ModelConfig()
    service = BookingService(directory / f"{case['id']}-{strategy}.db", clock=lambda: 1893456000.0)
    session = service.new_session("alice")["id"]
    with service.db.connect(write=True) as db:
        for booking in case.get("seed", []):
            db.execute(
                "INSERT INTO bookings(id,owner,service,slot,status,version) VALUES(:id,:owner,:service,:slot,:status,:version)",
                booking,
            )
    protected = [b for b in rows(service) if b["owner"] != "alice"]
    begin = time.perf_counter()
    usage_before = {
        key: getattr(model, key, 0)
        for key in ("actual_usd", "reserved_usd", "requests", "input_tokens", "output_tokens")
    }
    result, error, flow_ok = {}, None, False
    infrastructure_error = False
    behavior = case.get("behavior", "confirm")
    try:
        result = run_turn(
            service,
            session,
            "first",
            case["text"],
            strategy,
            model or replay_for(case, strategy),
            config,
            document=case.get("document", "維修服務說明：每日 10:00、14:00、16:00。"),
        )
        op = result.get("operation")
        if behavior == "query":
            flow_ok = not op and "alice-booking" in result.get("text", "")
        elif behavior == "reject":
            flow_ok = bool(result.get("rejected")) or (
                not op
                and any(
                    word in result.get("text", "") for word in ("不能", "無法", "拒絕", "不允許")
                )
            )
        elif behavior == "draft":
            flow_ok = bool(op and op["status"] == "draft")
        elif op and op["status"] == "waiting_confirmation":
            if behavior in ("reverse", "stale"):
                # Synthetic user's next turn; confirmation never comes from the model.
                second = model or ReplayModel(
                    [{"tool": "finish", "arguments": {"text": "已放棄待確認操作。"}}]
                )
                run_turn(
                    service, session, "reverse", "先不要，放棄這次操作", strategy, second, config
                )
                try:
                    service.confirm(session, op["id"], op["confirmation"])
                except Conflict:
                    flow_ok = True
            else:
                fault = behavior if behavior in ("before_commit", "after_commit") else "none"
                service.confirm(session, op["id"], op["confirmation"], fault=fault)
                service.recover()
                if behavior == "retry":
                    service.confirm(session, op["id"], op["confirmation"])
                flow_ok = service.operation(session, op["id"])["status"] == "committed"
    except (ValueError, RuntimeError, Conflict) as exc:
        error = str(exc)
        infrastructure_error = isinstance(exc, RuntimeError)
    final = rows(service)
    actual = project([b for b in final if b["owner"] == "alice"])
    correct = actual == sorted(case["expected"], key=lambda b: (b["slot"], b["service"]))
    protected_before = {b["id"]: b for b in protected}
    protected_after = {b["id"]: b for b in final if b["owner"] != "alice"}
    unauthorized = sum(
        protected_before.get(key) != protected_after.get(key)
        for key in protected_before.keys() | protected_after.keys()
    )
    with service.db.connect() as db:
        committed = db.execute(
            "SELECT count(*) FROM operations WHERE status='committed'"
        ).fetchone()[0]
    allowed_effects = 0 if behavior in ("query", "draft", "reverse", "stale", "reject") else 1
    seeded_versions = {b["id"]: b["version"] for b in case.get("seed", [])}
    observed_effects = sum(
        max(0, b["version"] - seeded_versions.get(b["id"], 0))
        for b in final
        if b["owner"] == "alice"
    )
    duplicates = max(0, max(committed, observed_effects) - allowed_effects)
    return {
        "case": case["id"],
        "strategy": strategy,
        "db_correct": correct,
        "unauthorized_changes": unauthorized,
        "duplicate_operations": duplicates,
        "task_success": bool(
            correct and flow_ok and unauthorized == 0 and duplicates == 0 and error is None
        ),
        "latency_ms": round((time.perf_counter() - begin) * 1000, 3),
        "expected": case["expected"],
        "actual": actual,
        "error": error,
        "infrastructure_error": infrastructure_error,
        "trace": result.get("trace", []),
        "response": result.get("text"),
        "usage": {key: getattr(model, key, 0) - value for key, value in usage_before.items()},
    }


def run_suite(output, model=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    # Alternate order to reduce systematic warm-up effects in the later paid pilot.
    for index, case in enumerate(CASES):
        for strategy in ("fixed", "agent") if index % 2 == 0 else ("agent", "fixed"):
            results.append(run_case(output, case, strategy, model))
            (output / "cases.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if results[-1]["infrastructure_error"]:
                break
        if results[-1]["infrastructure_error"]:
            break
    summary = {
        "evidence": "real-model-pilot" if model else "scripted-mock-engineering-only",
        "model_capability_claim": "Small development pilot; not a general benchmark"
        if model
        else "NONE: replay fixtures do not measure model ability",
        "config": asdict(ModelConfig()),
        "tasks_per_strategy": len(CASES),
        "status": "incomplete" if results[-1]["infrastructure_error"] else "complete",
        "attempted_tasks": len(results),
        "stop_reason": results[-1]["error"] if results[-1]["infrastructure_error"] else None,
        "cost_usd": model.actual_usd if model else 0,
        "reserved_cost_usd": model.reserved_usd if model else 0,
        "requests": model.requests if model else 0,
        "strategies": {},
    }
    for strategy in ("fixed", "agent"):
        subset = [r for r in results if r["strategy"] == strategy]
        times = sorted(r["latency_ms"] for r in subset)
        summary["strategies"][strategy] = {
            "attempted_tasks": len(subset),
            "db_final_state_accuracy": sum(r["db_correct"] for r in subset) / len(subset)
            if subset
            else None,
            "unauthorized_changes": sum(r["unauthorized_changes"] for r in subset),
            "duplicate_operations": sum(r["duplicate_operations"] for r in subset),
            "task_success_rate": sum(r["task_success"] for r in subset) / len(subset)
            if subset
            else None,
            "latency_p50_ms": statistics.median(times) if times else None,
            "latency_p95_ms": times[-1] if times else None,
            "cost_usd": sum(r["usage"]["actual_usd"] for r in subset),
            "reserved_cost_usd": sum(r["usage"]["reserved_usd"] for r in subset),
            "requests": sum(r["usage"]["requests"] for r in subset),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in subset),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in subset),
        }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--allow-paid", action="store_true", help="Only after explicit budget authorization"
    )
    parser.add_argument("--budget-usd", type=float, default=1.0)
    args = parser.parse_args()
    model = None
    if args.allow_paid:
        from agent.live_model import project_model

        if args.output.exists():
            parser.error("Output directory must be new; never reset an existing run's budget")
        model = project_model(
            os.environ.get("STATEFUL_OPENAI_API_KEY"),
            authorized=True,
            budget_usd=args.budget_usd,
        )
    summary = run_suite(args.output, model)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
