import json
import subprocess
import sys

import pytest

from research_state import BudgetExceeded, BudgetLedger, FileLock, atomic_json, read_json


def test_reservations_prevent_parallel_overspend_and_resume_preserves_usage(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json", 4)
    a = ledger.reserve(3, "fable:generation")
    resumed = BudgetLedger(ledger.path, 4)
    with pytest.raises(BudgetExceeded):
        resumed.reserve(2, "astra:review")
    ledger.settle(a, 1.5, {"tokens": 20})
    b = resumed.reserve(2, "astra:review")
    resumed.settle(b)  # No reported dollar charge does not mean free.
    assert resumed.spent == 3.5
    assert resumed.remaining == 0.5
    assert resumed.snapshot()["reported_cost"] == 1.5
    assert resumed.snapshot()["calls"] == 2


def test_reservations_survive_crash_and_cannot_reset_budget(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json", 3)
    ledger.reserve(3, "interrupted-call")
    assert BudgetLedger(ledger.path, 3).remaining == 0
    with pytest.raises(ValueError, match="preserve"):
        BudgetLedger(ledger.path, 5)


def test_actual_overrun_is_reported_not_hidden(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json", 2)
    a = ledger.reserve(2, "call")
    ledger.settle(a, 3)
    assert ledger.spent == 3
    assert ledger.remaining == 0
    with pytest.raises(BudgetExceeded):
        ledger.reserve(0.1, "next")


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True, "2"])
def test_reject_invalid_budget(invalid, tmp_path):
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / "budget.json", invalid)


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text("{truncated", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        BudgetLedger(path, 3)


def test_atomic_write_does_not_replace_good_state_with_nan(tmp_path):
    path = tmp_path / "state.json"
    atomic_json(path, {"good": 1})
    with pytest.raises(ValueError):
        atomic_json(path, {"bad": float("nan")})
    assert read_json(path) == {"good": 1}


def test_lock_excludes_another_process_and_releases(tmp_path):
    path = tmp_path / "exclusive.lock"
    code = "from research_state import FileLock; import sys;\nwith FileLock(sys.argv[1], timeout=0): print('acquired')"
    with FileLock(path):
        blocked = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, timeout=10)
        assert blocked.returncode != 0
        assert b"Another process holds" in blocked.stderr
    released = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, timeout=10)
    assert released.returncode == 0
    assert b"acquired" in released.stdout
