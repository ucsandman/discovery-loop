"""Exogenous edge tags for the candidate critique, and the three verdicts it may return.

Why this module exists
----------------------
The critique step used to hand a reviewer the candidate code and ask it to find
problems. That is the shape of review a measurement has since shown to be
systematically blind: a reviewer catches what the specification named, and when
an obligation was never written down it does not fail to reason — it reasons
correctly over an input that does not contain the answer, and reports the same
confidence it uses when it is right. Asking a second model, a stronger model, or
the same model twice does not recover the missing information.

What does work is telling the reviewer, up front and from outside its own
judgment, which questions this problem's specification does not settle. That is
the whole of the intervention here: a fixed list of edges per problem, appended
to the prompt, and three verdicts instead of two.

Two things this module deliberately does NOT do, both because they were measured
and found wanting:

* It never asks the reviewer to abstain when it feels unsure. Self-assessed
  uncertainty fires on whatever ambiguity the model happens to notice and
  essentially never on the actual blind spot — a model cannot feel a blind spot.
  The tag has to come from the artifact.
* It never asks the reviewer to argue against its own verdict. On a capable model
  that is inert at best, and in one recorded case it talked a reviewer out of a
  correct catch.

A useful property of tagging: it routes correctly even when the reviewer names
the wrong reason. Reviewers handed these tags have deferred while citing an
unrelated concern — wrong diagnosis, right action. That is exactly what a blind
spot needs, because a reviewer that could name the true edge was never blind.
"""

PASS = "pass"
FLAG = "flag"
INSUFFICIENT_SPEC = "insufficient_spec"

VERDICTS = (PASS, FLAG, INSUFFICIENT_SPEC)

# Edges that an optimization-solver specification in this repo does not settle,
# and that the verifier does not settle either. Each is here because the correct
# behavior cannot be recovered from the problem definition plus general
# programming knowledge — a reviewer reading the code has no basis to call any
# particular choice wrong.
#
# Kept SHORT on purpose. A false tag is not free: it makes a capable reviewer
# defer on a real, spec-determined bug about a third of the time, so precision
# here is load-bearing and a long list is worse than a short one. Anything the
# problem definition or the verifier already decides does not belong here.
NON_INFERABLE_BASELINE = (
    "Tie-breaking between two moves of equal cost: the spec does not say which wins, "
    "so a change that reorders equal-cost candidates is neither right nor wrong by the spec.",
    "Feasibility tolerance: whether a solution a hair over capacity (1e-9) is feasible "
    "is not stated anywhere, so tightening or loosening the comparison is unjudgeable.",
    "Behavior at the time limit: whether to return the best-so-far or nothing at all "
    "is not specified, so a change to what happens on timeout cannot be checked.",
    "Determinism under a fixed seed: the spec does not require two runs with the same "
    "seed to agree, so introducing or removing nondeterminism violates nothing stated.",
    "A candidate that exactly ties the incumbent: the spec does not say whether a tie "
    "counts as an improvement, so accept-on-tie and reject-on-tie are equally defensible.",
)


def edges_for(plugin):
    """Return the non-inferable edges to tag for this problem.

    A plugin may declare its own ``NON_INFERABLE_EDGES`` (a sequence of strings);
    they are added to the shared baseline rather than replacing it, because the
    baseline edges are properties of how every problem here is specified, not of
    any one problem.
    """
    extra = getattr(plugin, "NON_INFERABLE_EDGES", ()) or ()
    if isinstance(extra, str):  # a single edge written without a wrapping tuple
        extra = (extra,)
    seen = []
    for edge in tuple(NON_INFERABLE_BASELINE) + tuple(extra):
        text = str(edge).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def critique_prompt(code, edges):
    """Build the critique prompt: the code, the exogenous tags, and three verdicts."""
    tagged = "\n".join(f"  {i + 1}. {edge}" for i, edge in enumerate(edges))
    return (
        "Review this solver change for correctness, benchmark-specific tuning, and likely "
        "failure modes. Do not write replacement code.\n"
        "\n"
        "Before you read the code: the following questions are NOT answered by this "
        "problem's specification or its verifier. They were identified ahead of time, "
        "not by you. If the change turns on one of them, there is nothing to check it "
        "against, and saying so is the correct answer — not a failure to analyze.\n"
        "\n"
        f"{tagged}\n"
        "\n"
        "End your review with a single final line, exactly one of:\n"
        f"  VERDICT: {PASS.upper()}                — the change is sound against what the spec does state\n"
        f"  VERDICT: {FLAG.upper()}                — a concrete defect, judged against something the spec states\n"
        f"  VERDICT: {INSUFFICIENT_SPEC.upper()}   — the change turns on one of the questions above\n"
        "\n"
        "Do not argue against your own verdict afterwards, and do not soften a FLAG "
        "into a PASS on reflection. State it once.\n"
        "\n" + code
    )


def parse_disposition(text):
    """Read the verdict off a critique.

    Returns one of ``VERDICTS``, or ``None`` when no verdict line is present.
    A missing verdict is NOT a pass — the caller treats it as an undischarged
    check, for the same reason a test that did not run is not a green one.

    The last verdict line wins, so a reviewer that restates its conclusion at the
    end is read correctly. FLAG is sticky: once a review has flagged a defect, a
    later PASS in the same text cannot clear it. That asymmetry is deliberate —
    the recorded failure is a reviewer talking itself out of a correct catch, and
    never the reverse.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    found = []
    for raw in text.splitlines():
        line = raw.strip().rstrip(".").upper()
        if not line.startswith("VERDICT:"):
            continue
        value = line[len("VERDICT:") :].strip()
        for verdict in VERDICTS:
            if value.startswith(verdict.upper()):
                found.append(verdict)
                break
    if not found:
        return None
    if FLAG in found:
        return FLAG
    return found[-1]


def status_for(disposition, current="promising"):
    """Map a verdict onto the candidate status the loop already understands.

    Two different things are being protected here and they deserve different
    consequences, so this function is deliberately narrower than
    ``ineligibility_reason`` below.

    A FLAG or an INSUFFICIENT_SPEC demotes the candidate to
    ``promising_unreviewed``. Both mean the same thing for promotion: nobody has
    confirmed this change. Making it the champion on the strength of a review
    that found a defect, or one that could not judge the change at all, is
    exactly the confident green this whole mechanism exists to refuse.

    A verdict we could not READ does not demote. That is a formatting miss, not a
    finding, and this loop runs unattended overnight — silently stalling a whole
    night because a model omitted its last line would trade one failure mode for
    a worse one. It still costs the run its formal-trial eligibility (see
    ``ineligibility_reason``), which is the claim that actually must not be
    faked. Work continues; the result is not called confirmed.
    """
    if disposition in (FLAG, INSUFFICIENT_SPEC):
        return "promising_unreviewed"
    return current


def ineligibility_reason(disposition):
    """The trial-eligibility reason for a non-passing verdict, or None.

    Unlike ``status_for``, this covers the unreadable case too: a review whose
    conclusion nobody can read has not confirmed anything, and a formal trial
    that rests on it would be resting on nothing.
    """
    if disposition == FLAG:
        return "critique_flagged_defect"
    if disposition == INSUFFICIENT_SPEC:
        return "critique_insufficient_spec"
    if disposition is None:
        return "critique_verdict_unreadable"
    return None
