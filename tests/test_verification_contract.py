import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import verification_contract as vc


# --- edges_for ---------------------------------------------------------------


def test_baseline_edges_are_tagged_for_a_plugin_that_declares_none():
    edges = vc.edges_for(types.SimpleNamespace())
    assert edges == list(vc.NON_INFERABLE_BASELINE)


def test_plugin_edges_extend_the_baseline_rather_than_replacing_it():
    plugin = types.SimpleNamespace(NON_INFERABLE_EDGES=("Whether a split delivery is allowed.",))
    edges = vc.edges_for(plugin)
    assert edges[: len(vc.NON_INFERABLE_BASELINE)] == list(vc.NON_INFERABLE_BASELINE)
    assert edges[-1] == "Whether a split delivery is allowed."


def test_a_single_edge_written_as_a_bare_string_still_works():
    plugin = types.SimpleNamespace(NON_INFERABLE_EDGES="Whether ties are broken by index.")
    assert "Whether ties are broken by index." in vc.edges_for(plugin)


def test_duplicate_and_blank_edges_are_dropped():
    plugin = types.SimpleNamespace(
        NON_INFERABLE_EDGES=(vc.NON_INFERABLE_BASELINE[0], "  ", "", "New edge.", "New edge.")
    )
    edges = vc.edges_for(plugin)
    assert edges.count(vc.NON_INFERABLE_BASELINE[0]) == 1
    assert edges.count("New edge.") == 1
    assert "" not in edges


def test_the_baseline_stays_short_because_a_false_tag_costs_real_deferrals():
    # A false non-inferable tag makes a capable reviewer defer on a genuine,
    # spec-determined bug. Precision here is load-bearing; a long list is worse
    # than a short one. If this ever needs raising, raise it deliberately.
    assert len(vc.NON_INFERABLE_BASELINE) <= 8


# --- critique_prompt ---------------------------------------------------------


def test_prompt_carries_every_tag_and_all_three_verdicts():
    edges = ["Edge one.", "Edge two."]
    prompt = vc.critique_prompt("VALUE = 1\n", edges)
    assert "Edge one." in prompt
    assert "Edge two." in prompt
    assert "VALUE = 1" in prompt
    assert "VERDICT: PASS" in prompt
    assert "VERDICT: FLAG" in prompt
    assert "VERDICT: INSUFFICIENT_SPEC" in prompt


def test_prompt_states_the_tags_came_from_outside_the_reviewer():
    # The whole mechanism is that the tag is exogenous. A reviewer told to notice
    # its own uncertainty fires on salient ambiguity and never on the real blind
    # spot, which by definition it cannot feel.
    prompt = vc.critique_prompt("code", ["Edge."])
    assert "identified ahead of time, not by you" in prompt


def test_prompt_never_asks_the_reviewer_to_rebut_itself():
    # Self-disconfirmation is inert on a capable model and has been recorded
    # talking one out of a correct catch.
    prompt = vc.critique_prompt("code", ["Edge."]).lower()
    assert "do not argue against your own verdict" in prompt
    assert "if you are unsure" not in prompt
    assert "abstain if" not in prompt


# --- parse_disposition -------------------------------------------------------


def test_reads_each_verdict():
    assert vc.parse_disposition("looks fine\nVERDICT: PASS") == vc.PASS
    assert vc.parse_disposition("bug on line 4\nVERDICT: FLAG") == vc.FLAG
    assert vc.parse_disposition("turns on ties\nVERDICT: INSUFFICIENT_SPEC") == vc.INSUFFICIENT_SPEC


def test_tolerates_case_whitespace_and_a_trailing_period():
    assert vc.parse_disposition("   verdict: pass.  ") == vc.PASS


def test_a_review_with_no_verdict_line_reads_as_unknown_not_as_a_pass():
    assert vc.parse_disposition("reviewed") is None
    assert vc.parse_disposition("") is None
    assert vc.parse_disposition(None) is None


def test_a_flag_survives_a_later_pass_in_the_same_review():
    # The recorded failure is a reviewer talking itself out of a correct catch,
    # never the reverse. So the asymmetry is deliberate.
    text = "VERDICT: FLAG\non reflection this is fine\nVERDICT: PASS"
    assert vc.parse_disposition(text) == vc.FLAG


def test_the_last_verdict_wins_when_none_of_them_is_a_flag():
    assert vc.parse_disposition("VERDICT: PASS\nVERDICT: INSUFFICIENT_SPEC") == vc.INSUFFICIENT_SPEC


def test_an_unrecognized_verdict_word_is_not_read_as_a_verdict():
    assert vc.parse_disposition("VERDICT: probably fine") is None


# --- status_for / ineligibility_reason ---------------------------------------


def test_a_flag_and_an_unjudgeable_edge_both_block_promotion():
    assert vc.status_for(vc.FLAG) == "promising_unreviewed"
    assert vc.status_for(vc.INSUFFICIENT_SPEC) == "promising_unreviewed"


def test_a_pass_leaves_the_candidate_where_it_was():
    assert vc.status_for(vc.PASS) == "promising"
    assert vc.status_for(vc.PASS, "rejected") == "rejected"


def test_an_unreadable_verdict_does_not_demote_the_candidate():
    # It costs the run its trial eligibility instead. This loop runs unattended;
    # stalling a night over a missing last line is the worse failure.
    assert vc.status_for(None) == "promising"


def test_every_non_pass_verdict_costs_trial_eligibility():
    assert vc.ineligibility_reason(vc.FLAG) == "critique_flagged_defect"
    assert vc.ineligibility_reason(vc.INSUFFICIENT_SPEC) == "critique_insufficient_spec"
    assert vc.ineligibility_reason(None) == "critique_verdict_unreadable"
    assert vc.ineligibility_reason(vc.PASS) is None
