import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.service import BookingService, Conflict, Forbidden


@pytest.fixture
def svc(tmp_path):
    return BookingService(tmp_path / "test.db")


def draft(svc, session, action="create", slot="2030-01-08T10:00:00+08:00", **extra):
    turn = svc.begin_turn(
        session, extra.pop("request_id", "request-" + __import__("uuid").uuid4().hex), action
    )
    return svc.propose(
        session, turn["revision"], {"action": action, "slot": slot, "service": "冷氣維修", **extra}
    )


def commit(svc, session, op, fault="none"):
    return svc.confirm(session, op["id"], op["confirmation"], fault=fault)


def test_booking_changes_only_after_confirmation_and_supports_full_lifecycle(svc):
    session = svc.new_session("alice")["id"]
    op = draft(svc, session)
    assert svc.snapshot(session)["bookings"] == []
    result = commit(svc, session, op)
    booking = result["receipt"]["booking"]
    assert (booking["status"], booking["version"], booking["owner"]) == ("active", 1, "alice")
    op = draft(svc, session, "reschedule", "2030-01-09T14:00:00+08:00", booking_id=booking["id"])
    changed = commit(svc, session, op)["receipt"]["booking"]
    assert (changed["slot"], changed["version"]) == ("2030-01-09T14:00:00+08:00", 2)
    op = draft(svc, session, "cancel", booking_id=booking["id"])
    commit(svc, session, op)
    assert svc.snapshot(session)["bookings"][0]["status"] == "cancelled"
    with sqlite3.connect(svc.path) as db:
        assert db.execute("SELECT count(*) FROM bookings").fetchone()[0] == 1


def test_new_intent_blocks_old_confirmation_and_late_proposal(svc):
    session = svc.new_session("alice")["id"]
    old = draft(svc, session)
    turn = svc.begin_turn(session, "changed-mind", "先不要")
    with pytest.raises(Conflict):
        commit(svc, session, old)
    with pytest.raises(Conflict):
        svc.propose(
            session,
            turn["revision"] - 1,
            {"action": "create", "slot": "2030-01-08T10:00:00+08:00", "service": "冷氣維修"},
        )
    assert svc.snapshot(session)["bookings"] == []


def test_session_ownership_is_enforced_and_model_cannot_supply_owner(svc):
    alice = svc.new_session("alice")["id"]
    bob = svc.new_session("bob")["id"]
    op = draft(svc, alice)
    with pytest.raises(Forbidden):
        commit(svc, bob, op)
    booking = commit(svc, alice, op)["receipt"]["booking"]
    with pytest.raises(Forbidden):
        draft(svc, bob, "cancel", booking_id=booking["id"])
    with pytest.raises(ValueError):
        draft(svc, bob, user_id="alice")
    assert svc.snapshot(bob)["bookings"] == []


def test_retries_return_original_receipt_without_duplicate_effect(svc):
    session = svc.new_session("alice")["id"]
    op = draft(svc, session)
    first = commit(svc, session, op)
    assert commit(svc, session, op)["receipt"] == first["receipt"]
    assert len(svc.snapshot(session)["bookings"]) == 1
    a = svc.begin_turn(session, "same-request", "查詢")
    b = svc.begin_turn(session, "same-request", "查詢")
    assert a["revision"] == b["revision"]
    with pytest.raises(Conflict):
        svc.begin_turn(session, "same-request", "取消")


def test_racing_reschedules_cannot_overwrite_a_newer_booking(svc):
    a = svc.new_session("alice")["id"]
    booking = commit(svc, a, draft(svc, a))["receipt"]["booking"]
    b = svc.new_session("alice")["id"]
    op_a = draft(svc, a, "reschedule", "2030-01-09T10:00:00+08:00", booking_id=booking["id"])
    op_b = draft(svc, b, "reschedule", "2030-01-10T10:00:00+08:00", booking_id=booking["id"])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda pair: commit(svc, *pair), [(a, op_a), (b, op_b)]))
    assert sorted(x["status"] for x in results) == ["committed", "failed"]
    assert svc.snapshot(a)["bookings"][0]["version"] == 2


@pytest.mark.parametrize("fault", ["before_commit", "after_commit"])
def test_lost_response_is_reconciled_after_reopening_database(svc, fault):
    session = svc.new_session("alice")["id"]
    op = draft(svc, session)
    result = commit(svc, session, op, fault)
    assert result["delivery"] == "unknown"
    restored = BookingService(svc.path)
    restored.recover()
    recovered = restored.operation(session, op["id"])
    assert recovered["status"] == "committed"
    assert len(restored.snapshot(session)["bookings"]) == 1
    assert commit(restored, session, op)["receipt"] == recovered["receipt"]


def test_reversal_during_unknown_before_commit_prevents_recovery_write(svc):
    session = svc.new_session("alice")["id"]
    op = draft(svc, session)
    commit(svc, session, op, "before_commit")
    svc.begin_turn(session, "reversal", "先不要預約")
    svc.recover()
    assert svc.operation(session, op["id"])["status"] == "cancelled"
    assert svc.snapshot(session)["bookings"] == []


def test_slot_collision_fails_without_partial_write(svc):
    a = svc.new_session("alice")["id"]
    b = svc.new_session("bob")["id"]
    op_a, op_b = draft(svc, a), draft(svc, b)
    assert commit(svc, a, op_a)["status"] == "committed"
    assert commit(svc, b, op_b)["status"] == "failed"
    assert svc.snapshot(b)["bookings"] == []
