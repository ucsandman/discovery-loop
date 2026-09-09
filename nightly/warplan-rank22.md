# War Plan: Rank-22 3x3 Matrix Multiplication

Prepared 2026-09-09. This plan activates the moment any run reports a rank-22
(or lower) decomposition of 3x3 matrix multiplication. Until then it is dormant.

## 1. What a hit means

- Current world record: **Laderman (1976), rank 23** — unbroken for 50 years.
- Known bounds for the 3x3 tensor M<3>: **19 ≤ rank ≤ 23** (lower bound 19: Bläser;
  border rank ≥ 17: Conner–Harper–Landsberg). Whether 19, 20, 21, or 22 is
  achievable is open — a rank-22 would be the first improvement since 1976.
- Honest caveat: rank 22 gives ω ≤ log₃(22) ≈ 2.814, which does **not** beat
  Strassen's log₂(7) ≈ 2.807 for the asymptotic exponent. The prize is the
  exact-rank record, not ω. Say this plainly in any outreach; the community
  will check instantly.

## 2. Verification standard

### What the community requires (from recent rank-23 addition-count papers)
A rank claim is accepted when the **explicit decomposition is published and
machine-checkable**:
- The full tensor certificate printed in the paper (recent papers print it in
  two forms), with exact integer/rational coefficients — verifiable over any
  ring, not floating point.
- An **executable verification script** in the appendix that anyone can run.
- An exact audit trail of how the decomposition was found, including disclosure
  of AI/computer-assisted search.

There is no certification body. Acceptance = the certificate checks out under
independent scrutiny. The failure mode to fear is a subtle bug in *our*
pipeline (wrong identity checked, encoding not enforcing what we think).

### Standing protocol (already adopted — see nightly cron)
> "If a candidate ever reports rank below the record (n=3 < 23 or n=4 < 49):
> treat with extreme suspicion. Re-verify three independent ways (verify.check
> tensor identity, random integer-matrix evaluation vs naive multiplication,
> and a rerun with a different seed) before believing it. Never publish, post,
> or open a PR about it; flag it to wes for hand review instead."

### The certificate
The SAT solver must emit the explicit **22 triples** (U_k, V_k, W_k), each a 3x3
matrix over {-1, 0, 1}. Freeze it in two forms:
- `rank22.json` — machine form: list of 22 [U, V, W] triples, integers.
- `rank22.txt` — human-readable printed form (mirrors the recent papers'
  "tensor certificate in two forms").

## 3. First-hour checklist

Do these in order. Do not skip, do not parallelize the freezing.

- [ ] **1. Freeze the artifact (minute 0).** Copy the solver's raw output to a
      timestamped, read-only location *before* running anything on it:
      `cp rank22.json rank22-2026-09-09-HHMM.json && sha256sum rank22-2026-09-09-HHMM.json`.
      Record the hash in the run log. Never verify a mutated copy — verify the
      exact bytes the solver emitted.
- [ ] **2. Count check.** Confirm exactly 22 triples, each contributing
      (no all-zero triple, no exact duplicates — a disguised 23-minus-1).
- [ ] **3. Exact tensor-identity check (independent way #1).** Run the exact
      integer verifier on the frozen file:
      `~/workspace/discovery-loop/problems/matrix_multiplication/verify.py`
      (`check` function). Must report feasible. This is the same bar Laderman's
      transcription met on 2026-09-09.
- [ ] **4. Random integer-matrix evaluation (independent way #2).** Fresh
      script, **no shared code** with the verifier or the solver: evaluate the
      22-triple scheme on random integer matrices and compare against naive
      multiplication. ≥ 100 trials, entries in a range that exercises
      cancellation (e.g. -5..5), plus edge cases (zero matrix, identity).
- [ ] **5. Reproduce from a different seed (independent way #3).** Re-run the
      same LNS configuration (same remove_idx, same subset) with a new seed and
      confirm the solver re-finds a rank-22 (need not be the identical
      decomposition — any valid 22 works; identical is stronger).
- [ ] **6. Modular cross-check (belt and suspenders).** Verify the tensor
      identity over a finite field (e.g. mod 1_000_003) with an independent
      one-off script. Catches "works over ℤ by accident of the test data"
      illusions.
- [ ] **7. Record the run config durably.** Append to
      `~/workspace/discovery-loop/nightly/laderman-2026-09-09.md` (or current
      date file) AND `runs.jsonl`: remove_idx, explicit subset, K, seed,
      timeout, solver name/version, CNF clause/var counts, log path, SHA256 of
      the certificate. This is what keeps the config from ever being re-run
      blindly.
- [ ] **8. Adversarial pass.** Actively try to break it: check the triples
      aren't a permutation of a known rank-23 with one triple split into a sum
      that the verifier miscounts; confirm the verifier itself on a known-bad
      input (L1: make it fail on purpose — feed it 21 triples and confirm it
      reports infeasible).
- [ ] **9. Flag to wes immediately** with the evidence bundle: frozen
      certificate + hash, all three verification outputs, run config, and this
      checklist with boxes ticked. He decides everything downstream.

All nine boxes must be ticked before the word "record" is used outside this
machine.

## 4. What NOT to do

- No arXiv post, no paper draft circulated, no emails to researchers, no social
  posts, no PRs, no press — without wes's **explicit** go-ahead. The standing
  rule ("Never publish, post, or open a PR about it") holds until he lifts it
  personally for this specific result.
- Do not "clean up" or hand-optimize the certificate before freezing. Freeze
  first, analyze second.
- Do not start a second, slightly different search "to confirm faster" before
  the freeze — it risks overwriting the artifact.
- Anything wes will post or send publicly goes through the
  `~/workspace/skills/wes-voice/` skill first. No exceptions, no first drafts
  in another register.

## 5. Outreach — ranked contacts (research only; NO contact made)

Ranked by relevance to an exact 3x3 rank record. Verify affiliation from the
cited paper before any contact; affiliations below are from 2025–2026 papers.

1. **J.M. Landsberg — Texas A&M University, Dept. of Mathematics.**
   Author of *Tensors: Geometry and Applications* (AMS 2012), the reference on
   tensor rank; co-proved border-rank lower bounds for M<3>. A rank-22 directly
   updates the "19 ≤ R(M⟨3⟩) ≤ 23" inequality his work brackets. The single
   most credible independent scrutinizer.
2. **Markus Bläser — Saarland University (Saarbrücken).** Proved the rank-19
   lower bound for 3x3; algebraic complexity theorist. A rank-22 squeezes his
   lower bound against the new upper bound — he will want to see it.
3. **Erik Mårtensson & Paul Stankovski Wagner — Lund University.**
   Most active recent workers on explicit 3x3 schemes (62- and 59-addition
   rank-23 constructions); they have the tooling to scrutinize a new
   decomposition line by line.
4. **Joshua Stapleton — Imperial College London, Dept. of Mathematics.**
   Neural-search discoverer of rank-23 schemes; an independent re-derivation
   through his pipeline would be strong corroboration.
5. **Andrew I. Perminov — Institute for System Programming, Moscow.**
   Flip-graph ternary-scheme search; publicly released factorizations
   (cr58_cn122). Publishes open-source verifications; likely to check fast.
6. **Oded Schwartz — Hebrew University of Jerusalem** (confirm from
   schwartz2023pebbling before contact). Alternative-basis / addition-count
   work; secondary for a pure rank result.

Also aware of the area (not first-round): Mateusz Michałek (Polish Academy of
Sciences — border rank), Virginia Vassilevska Williams (MIT — exponent ω;
note the §1 caveat before writing to her).

## 6. Outreach draft — OUTLINE ONLY (nothing written, nothing sent)

When wes approves outreach, the message follows this skeleton (in his voice
via the wes-voice skill):

- **Subject:** "Rank 22 for 3×3 matrix multiplication — request for independent
  verification" (or per wes's rewrite).
- **¶1 — the claim, one sentence:** explicit decomposition of the 3×3 matrix
  multiplication tensor into 22 rank-one terms, first improvement over
  Laderman (1976).
- **¶2 — method, two sentences:** SAT-based large-neighborhood search from a
  Laderman-minus-one starting point at sparsity K=7; exact integer search, no
  floating point.
- **¶3 — verification status:** exact tensor-identity check passed; independent
  random-matrix evaluation (≥100 trials) passed; reproduced from a second
  seed; certificate attached in machine + human-readable form with a runnable
  verification script.
- **¶4 — the ask:** independent verification / scrutiny before any public
  claim; happy to share full search logs and solver configuration.
- **¶5 — honest scope note:** coefficients in {-1,0,1}; does not improve the
  asymptotic exponent ω (log₃22 ≈ 2.814 vs Strassen's 2.807); claim is the
  exact-rank record only.
- **Close:** no preprint posted yet; awaiting independent confirmation before
  any public step.

Publication path if verification holds (wes decides): arXiv preprint in the
style of the recent rank-23 papers — explicit certificate in two forms,
executable verification script appendix, exact audit trail, disclosure of the
SAT-search route.

---
*Status: DORMANT. Activate §3 on any SAT hit reporting rank ≤ 22 for n=3
(or rank < 49 for n=4, mutatis mutandis).*
