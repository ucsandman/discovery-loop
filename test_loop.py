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


# ── publish: the in-loop path only pushes; the maintainer email is batched per slot by night.py ──
def test_loop_publish_is_push_only():
    import types

    calls = []
    orig = subprocess.Popen
    subprocess.Popen = lambda cmd, **_: calls.append(cmd) or None
    try:
        fake = types.SimpleNamespace(name="cvrp", runs=os.path.join(HERE, "runs-cvrp"))
        loop.Loop.publish(fake)
    finally:
        subprocess.Popen = orig
    assert len(calls) == 1
    assert calls[0][1].endswith("publish.py")
    assert "--push-only" in calls[0]


def test_night_publish_slot_emails_full():
    import night

    calls = []
    orig = subprocess.Popen
    subprocess.Popen = lambda cmd, **_: calls.append(cmd) or None
    try:
        night.publish_slot("cvrp")
    finally:
        subprocess.Popen = orig
    assert len(calls) == 1
    assert calls[0][1].endswith("publish.py")
    assert "--push-only" not in calls[0]
    assert calls[0][calls[0].index("--problem") + 1] == "cvrp"


# ── retro: the prompt sees every idea ever tried and the last retro's Next block ──
def _fake_history(n):
    return [
        {"iter": i, "status": "seed" if i == 0 else "rejected", "total": -1.0, "cost": 1.0, "idea": f"idea number {i}"}
        for i in range(n)
    ]


def test_compress_history_surfaces_ideas_older_than_the_full_window():
    old = loop.compress_history(_fake_history(20))
    assert "idea number 3" in old, old  # older than the last 12
    assert "idea number 19" not in old, old  # the full block already carries the recent ones
    assert old.startswith("iter 7 "), old  # newest of the old ones first


def test_read_latest_retro_returns_last_sections_lessons_and_next(tmp_path):
    import retro

    path = str(tmp_path / "cvrp.md")
    retro.append_section(path, "## 2026-09-04 cvrp: iters 0-3", "### What worked\n- a\n### Next\n1. old direction")
    retro.append_section(
        path,
        "## 2026-09-05 cvrp: iters 4-8",
        "### What worked\n- b\n### Lessons\n- lesson L\n### Next\n1. [kind: representation] new direction",
    )
    got = loop.read_latest_retro(path)
    assert "lesson L" in got and "new direction" in got, got
    assert "old direction" not in got and "- b" not in got, got
    assert loop.read_latest_retro(str(tmp_path / "missing.md")) == ""


def test_build_prompt_carries_old_ideas_and_retro(tmp_path, monkeypatch):
    import types

    import retro

    champ = tmp_path / "solver.py"
    champ.write_text("print('champ')", encoding="utf-8")
    retro.append_section(
        str(tmp_path / "fake.md"),
        "## 2026-09-05 fake: iters 0-1",
        "### Lessons\n- L1\n### Next\n1. [kind: time allocation] spend it all on X-n459",
    )
    monkeypatch.setattr(loop, "retro_path", lambda name: str(tmp_path / f"{name}.md"))
    fake = types.SimpleNamespace(
        P=types.SimpleNamespace(PROMPT="P", MAXIMIZE=True, TOTAL_DESC="sum", TASK="T"),
        name="fake",
        champ=str(champ),
        scoreboard=lambda targets, rec, last: [("t1", 1.0, 0.9, None, -0.1)],
    )
    prompt = loop.Loop.build_prompt(fake, ["t1"], {}, None, _fake_history(20))
    assert "PREVIOUSLY TRIED" in prompt and "idea number 2" in prompt, prompt
    assert "LAST RETRO" in prompt and "spend it all on X-n459" in prompt and "[NEXT #k]" in prompt, prompt


def test_retro_prompt_lists_every_idea_and_the_brainstorm_rules():
    import types

    import retro

    P = types.SimpleNamespace(PROMPT="context", MAXIMIZE=False, TOTAL_DESC="gap")
    prompt = retro.build_retro_prompt(P, "cvrp", _fake_history(30), "board", "code", since_iter=25)
    assert all(f"idea number {i}" in prompt for i in range(30)), "every idea, all time"
    assert "differ in KIND" in prompt and "### Next" in prompt and "5 iterations" in prompt, prompt


def test_night_retro_slot_runs_retro_synchronously_with_since_iter():
    import night

    calls = []
    orig = subprocess.run
    subprocess.run = lambda cmd, **_: calls.append(cmd) or None
    try:
        night.retro_slot("cvrp", 7)
    finally:
        subprocess.run = orig
    assert len(calls) == 1 and calls[0][1].endswith("retro.py"), calls
    assert calls[0][calls[0].index("--since-iter") + 1] == "7"


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
