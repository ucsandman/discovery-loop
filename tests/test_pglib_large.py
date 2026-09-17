"""Opt-in large PGLib cases: accepted by the prompt gate, never part of the nightly target list."""

from problem_loader import load_problem


def test_large_targets_are_opt_in_and_prompted():
    problem = load_problem("pglib_opf")
    assert problem.DEVELOPMENT == problem.TARGETS
    assert set(problem.LARGE_TARGETS).isdisjoint(problem.TARGETS)
    assert all(name.startswith("pglib_opf_case2") for name in problem.LARGE_TARGETS)
    small = problem.prompt_for_targets(problem.TARGETS[:1])
    large = problem.prompt_for_targets(problem.LARGE_TARGETS[:1])
    assert "LARGE CASES" not in small
    assert "LARGE CASES" in large
    assert problem.LARGE_DEFAULTS["time"] > problem.DEFAULTS["time"]


def test_large_targets_have_published_baselines():
    problem = load_problem("pglib_opf")
    records = problem.records_load()
    for name in problem.LARGE_TARGETS:
        assert name in records and records[name] > 0


def test_research_gate_accepts_opt_in_targets():
    import loop as loop_module

    problem = load_problem("pglib_opf")
    selectable = set(problem.DEVELOPMENT) | set(getattr(problem, "LARGE_TARGETS", ()))
    assert set(problem.LARGE_TARGETS) <= selectable
    source = open(loop_module.__file__, encoding="utf-8").read()
    assert 'getattr(plugin, "LARGE_TARGETS", ())' in source
