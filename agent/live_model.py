"""Small, durable allowance for the explicitly enabled local model demo."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from agent.openai_model import BudgetExceeded, OpenAIModel


class LiveModel:
    def __init__(
        self,
        directory,
        *,
        api_key,
        authorized=False,
        budget_usd=1.0,
        max_requests=144,
        baseline=None,
        transport=None,
    ):
        if not authorized or not api_key:
            raise PermissionError("Enable the authorized demo and provide its dedicated key")
        if not (0 < budget_usd <= 1 and 0 < max_requests <= 144):
            raise ValueError("Local allowance is limited to USD 1 and 144 requests")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.api_key, self.transport = api_key, transport
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, budget REAL, requests INTEGER)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, reserved REAL NOT NULL, actual REAL)"
            )
            policy = db.execute("SELECT budget,requests FROM policy WHERE id=1").fetchone()
            if policy is None:
                db.execute("INSERT INTO policy VALUES(1,?,?)", (budget_usd, max_requests))
                # Baseline is imported atomically with the allowance, never on each restart.
                if baseline is not None:
                    for line in Path(baseline).read_text(encoding="utf-8").splitlines():
                        row = json.loads(line)
                        key = f"pilot-{row['request']}"
                        if row["state"] == "reserved":
                            db.execute(
                                "INSERT INTO calls VALUES(?,?,NULL)", (key, row["reserved_usd"])
                            )
                        elif row["state"] == "response":
                            db.execute(
                                "UPDATE calls SET actual=? WHERE id=?", (row["actual_usd"], key)
                            )
            elif tuple(policy) != (budget_usd, max_requests):
                raise ValueError("Existing allowance cannot be silently reset or changed")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.directory / "allowance.db", timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _status(self, db):
        budget, limit = db.execute("SELECT budget,requests FROM policy WHERE id=1").fetchone()
        count, reserved, actual, unknown, over = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(actual),0),"
            "COALESCE(SUM(actual IS NULL),0),COALESCE(SUM(actual > reserved),0) FROM calls"
        ).fetchone()
        return {
            "requests": count,
            "reserved_usd": reserved,
            "actual_usd": actual,
            "unknown_requests": unknown,
            "blocked": bool(over),
            "budget_usd": budget,
            "max_requests": limit,
        }

    def status(self):
        with self._db() as db:
            return self._status(db)

    def respond(self, messages, config):
        reserve = OpenAIModel.reservation(messages, config)
        request_id = uuid.uuid4().hex
        with self._db() as db:
            usage = self._status(db)
            if (
                usage["blocked"]
                or usage["requests"] >= usage["max_requests"]
                or usage["reserved_usd"] + reserve > usage["budget_usd"]
            ):
                raise BudgetExceeded("Local model allowance reached; no request sent")
            db.execute("INSERT INTO calls VALUES(?,?,NULL)", (request_id, reserve))
        # No database transaction is held across the network. A crash leaves the
        # reservation intact. Each transport attempt has its own immutable ledger.
        adapter = OpenAIModel(
            self.api_key,
            self.directory / f"{request_id}.jsonl",
            authorized=True,
            budget_usd=reserve,
            max_requests=1,
            transport=self.transport,
        )
        try:
            return adapter.respond(messages, config)
        finally:
            rows = [
                json.loads(line) for line in adapter.ledger.read_text(encoding="utf-8").splitlines()
            ]
            response = next((row for row in rows if row["state"] == "response"), None)
            if response is not None:
                with self._db() as db:
                    db.execute(
                        "UPDATE calls SET actual=? WHERE id=?", (response["actual_usd"], request_id)
                    )
