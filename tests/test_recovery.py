import json
import subprocess
import sys
import time

import pytest
from test_service import commit, draft

from agent.service import BookingService, Conflict


def test_expired_confirmation_cannot_execute_or_resume(tmp_path):
    clock = [1800000000.0]
    svc = BookingService(tmp_path / "expiry.db", clock=lambda: clock[0])
    session = svc.new_session("alice")["id"]
    op = draft(svc, session)
    commit(svc, session, op, "before_commit")
    clock[0] += 301
    svc.recover()
    assert svc.operation(session, op["id"])["status"] == "cancelled"
    assert svc.snapshot(session)["bookings"] == []
    with pytest.raises(Conflict):
        commit(svc, session, op)


@pytest.mark.parametrize("fault", ["before_commit", "after_commit"])
def test_real_process_termination_then_restart_preserves_one_effect(tmp_path, fault):
    database = tmp_path / "restart.db"
    marker = tmp_path / "ready.json"
    # Only this test's own process is terminated. The marker is written after the
    # real service has persisted the fault boundary, never after a simulated write.
    script = """
import json,sys,time
from pathlib import Path
from agent.service import BookingService
svc=BookingService(sys.argv[1])
session=svc.new_session('alice')['id']
turn=svc.begin_turn(session,'request','create')
op=svc.propose(session,turn['revision'],{'action':'create','service':'冷氣維修','slot':'2030-01-08T10:00:00+08:00'})
svc.confirm(session,op['id'],op['confirmation'],fault=sys.argv[3])
Path(sys.argv[2]).write_text(json.dumps({'session':session,'op':op['id']}))
time.sleep(30)
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(database), str(marker), fault])
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            assert child.poll() is None, "test worker exited before persisting the boundary"
            time.sleep(0.02)
        assert marker.exists()
    finally:
        child.kill()
        child.wait(timeout=5)
    context = json.loads(marker.read_text())
    check = """
import json,sys
from agent.service import BookingService
s=BookingService(sys.argv[1]);s.recover()
state=s.snapshot(sys.argv[2])
print(json.dumps({'bookings':state['bookings'],'op':s.operation(sys.argv[2],sys.argv[3])}))
"""
    result = subprocess.run(
        [sys.executable, "-c", check, str(database), context["session"], context["op"]],
        capture_output=True,
        text=True,
        check=True,
    )
    state = json.loads(result.stdout)
    assert len(state["bookings"]) == 1
    assert state["bookings"][0]["version"] == 1
    assert state["op"]["receipt"]["booking"]["id"] == state["bookings"][0]["id"]


def test_committed_action_requires_new_confirmation_for_compensation(tmp_path):
    svc = BookingService(tmp_path / "compensation.db")
    session = svc.new_session("alice")["id"]
    op = draft(svc, session)
    booking = commit(svc, session, op)["receipt"]["booking"]
    with pytest.raises(Conflict):
        svc.abandon(session, op["id"])
    cancellation = draft(svc, session, "cancel", booking_id=booking["id"])
    assert svc.snapshot(session)["bookings"][0]["status"] == "active"
    commit(svc, session, cancellation)
    assert svc.snapshot(session)["bookings"][0]["status"] == "cancelled"
