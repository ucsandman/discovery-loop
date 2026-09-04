"""Tests for loop.py: call_model's CLI-failure handling and the plateau rule.

Runnable two ways:
    python test_loop.py       # prints PASS/FAIL per test
    pytest test_loop.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import loop  # noqa: E402


# ── call_model: CLI failures become no-code triples, not exceptions ──
def test_call_model_timeout_returns_no_code():
    orig = subprocess.run
    try:

        def raise_timeout(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=900)

        subprocess.run = raise_timeout
        code, cost, idea = loop.Loop.call_model("prompt", "claude-fable-5-1")
        assert code is None, code
        assert cost == 0.0, cost
        assert idea == "cli timeout after 900s", idea
    finally:
        subprocess.run = orig


def test_call_model_oserror_returns_no_code():
    orig = subprocess.run
    try:

        def raise_oserror(*_a, **_k):
            raise OSError("claude not found")

        subprocess.run = raise_oserror
        code, cost, idea = loop.Loop.call_model("prompt", "claude-fable-5-1")
        assert code is None, code
        assert cost == 0.0, cost
        assert "cli error" in idea, idea
    finally:
        subprocess.run = orig


# ── check_plateau: relative signal 3, no-code exclusion, window 0 ──
def _entry(iter_, status, total, cost=1.0):
    return {"iter": iter_, "status": status, "total": total, "cost": cost}


def test_plateau_relative_large_gain_is_not_plateau():
    # pglib-like: seed 0.00014 -> champion 0.0030 (20x), then three rejected. Not a plateau at window 4.
    history = [
        _entry(0, "seed", 0.00014, cost=0.0),
        _entry(1, "champion", 0.0030),
        _entry(2, "rejected", 0.0010),
        _entry(3, "rejected", 0.0009),
        _entry(4, "rejected", 0.0008),
    ]
    assert loop.check_plateau(history, 4, 0.01) is False


def test_plateau_flat_history_is_plateau():
    # champion equal to seed, then 5 rejected: no relative gain across window 6.
    history = [
        _entry(0, "seed", -3.26, cost=0.0),
        _entry(1, "champion", -3.26),
        _entry(2, "rejected", -3.30),
        _entry(3, "rejected", -3.30),
        _entry(4, "rejected", -3.30),
        _entry(5, "rejected", -3.30),
        _entry(6, "rejected", -3.30),
    ]
    assert loop.check_plateau(history, 6, 0.01) is True


def test_plateau_window_zero_never_triggers():
    history = [
        _entry(0, "seed", -3.26, cost=0.0),
        _entry(1, "rejected", -3.30),
        _entry(2, "rejected", -3.30),
        _entry(3, "rejected", -3.30),
        _entry(4, "rejected", -3.30),
        _entry(5, "rejected", -3.30),
        _entry(6, "rejected", -3.30),
    ]
    assert loop.check_plateau(history, 0, 0.01) is False


def test_plateau_ignores_no_code_entries():
    # 3 no-code (CLI timeouts) plus 2 rejected: only 2 count toward a window of 6, not enough data.
    history = [
        _entry(0, "seed", -3.26, cost=0.0),
        _entry(1, "no-code", 0.0, cost=0.0),
        _entry(2, "no-code", 0.0, cost=0.0),
        _entry(3, "no-code", 0.0, cost=0.0),
        _entry(4, "rejected", -3.30),
        _entry(5, "rejected", -3.30),
    ]
    assert loop.check_plateau(history, 6, 0.01) is False


def _main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _main()
