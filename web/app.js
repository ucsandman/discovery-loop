(() => {
  "use strict";

  const state = { csrf: "", status: null, evidence: [], selected: null, arc: null };
  const byId = (id) => document.getElementById(id);
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const setNotice = (element, text, error = false) => {
    element.textContent = text;
    element.classList.toggle("error", error);
  };
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const numberFrom = (value, fallback = 0) => finite(Number(value)) ? Number(value) : fallback;
  const titleCase = (value) => String(value || "unknown").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const formatAllowance = (value) => numberFrom(value).toFixed(2);
  const countText = (value) => Object.entries(value && typeof value === "object" ? value : {})
    .map(([name, count]) => `${name} ${numberFrom(count)}`).join("; ") || "—";
  const shareText = (value) => Object.entries(value && typeof value === "object" ? value : {})
    .map(([name, share]) => `${name} ${Math.round(numberFrom(share) * 100)}%`).join("; ") || "—";
  const tokenCount = (value) => {
    if (!value || typeof value !== "object") return 0;
    if (finite(value.total_tokens)) return value.total_tokens;
    const direct = numberFrom(value.input_tokens) + numberFrom(value.output_tokens);
    if (direct) return direct;
    return Object.values(value).reduce((sum, item) => sum + tokenCount(item), 0);
  };
  const formatEffect = (evidence) => {
    const confirmation = evidence.confirmation || {};
    const value = confirmation.median_gain ?? confirmation.median_improvement ?? confirmation.effect;
    if (!finite(value)) return "Not reported";
    const percent = Math.abs(value) <= 1 ? value * 100 : value;
    return `${percent > 0 ? "+" : ""}${percent.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}% median`;
  };
  const statusStamp = (label, kind) => {
    const span = node("span", `stamp ${kind}`, label);
    return span;
  };
  const dateText = (value) => {
    const dateOnly = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
    const date = dateOnly
      ? new Date(...value.split("-").map((part, index) => Number(part) - (index === 1 ? 1 : 0)))
      : value ? new Date(value) : new Date();
    if (Number.isNaN(date.valueOf())) return "Discovery review";
    return `Discovery review · ${new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "long", year: "numeric" }).format(date)}`;
  };

  async function api(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body) {
      init.headers["Content-Type"] = "application/json";
      init.headers["X-CSRF-Token"] = state.csrf;
    }
    const response = await fetch(path, init);
    let result;
    try { result = await response.json(); } catch { result = { message: "The dashboard returned an unreadable response." }; }
    if (!response.ok) throw new Error(result.message || `Request failed (${response.status}).`);
    return result;
  }

  function renderNight() {
    const status = state.status;
    const night = status.night_status || {};
    const control = status.control || {};
    const slots = Array.isArray(night.slots) ? night.slots : [];
    const completed = slots.filter((slot) => slot.status === "completed" || slot.exit_code === 0).length;
    const matchingEvidence = state.evidence.filter((item) => item.run_id === night.run_id);
    const slotIterations = slots.map((slot) => slot.night_iterations ?? slot.iterations).filter(finite);
    const evidenceIterations = matchingEvidence.map((item) => item.usage?.iterations).filter(finite);
    const iterations = [...slotIterations, ...evidenceIterations].reduce((sum, value) => sum + value, 0);
    const slotSpend = slots.map((slot) => slot.night_spend_usd ?? slot.spent_usd).filter(finite);
    const spend = finite(night.budget_used_api_equivalent)
      ? night.budget_used_api_equivalent
      : slotSpend.length ? slotSpend.reduce((sum, value) => sum + value, 0) : null;
    const tokens = tokenCount(night.usage || slots.map((slot) => slot.usage));
    const stamp = byId("night-stamp");
    const rawStatus = String(night.status || night.state || "").toLowerCase();
    let label = "Awaiting next run";
    let kind = "neutral";
    if (control.paused && rawStatus === "running") { label = "Pause requested"; kind = "warn"; }
    else if (control.paused) { label = "Research paused"; kind = "warn"; }
    else if (rawStatus === "running") { label = "Run in progress"; kind = "good"; }
    else if (night.finished || rawStatus === "completed") { label = "Run complete"; kind = "good"; }
    else if (["failed", "partial_failure", "error"].includes(rawStatus)) { label = "Review needed"; kind = "warn"; }
    stamp.className = `stamp ${kind}`;
    stamp.replaceChildren(node("span", "signal"), document.createTextNode(label));
    byId("night-summary").textContent = slots.length ? `${completed} of ${slots.length} studies finished` : "No active research night";
    const usageParts = [
      slotIterations.length || evidenceIterations.length ? `${iterations} iterations` : "Iterations not reported",
      spend === null ? "Allowance use not reported" : `${formatAllowance(spend)} reported total_cost_usd API-equivalent`,
    ];
    if (tokens) usageParts.push(`${new Intl.NumberFormat().format(tokens)} tokens`);
    byId("night-usage").textContent = slots.length ? usageParts.join(" · ") : "Historical results remain available below.";
    const logicalDate = night.scheduled_run_id || String(night.run_id || "").slice(0, 10);
    byId("dateline").textContent = dateText(/^\d{4}-\d{2}-\d{2}$/.test(logicalDate) ? logicalDate : status.generated_at);
    byId("pause").disabled = control.paused === true;
    byId("continue").disabled = control.paused !== true;
  }

  const requestedArcId = (() => {
    const value = new URLSearchParams(window.location.search).get("arc_problem");
    return value && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) ? value : null;
  })();

  const arcSearchText = (problem) => [
    problem.title, problem.field, problem.subfield, problem.summary,
    ...(Array.isArray(problem.tags) ? problem.tags : []),
    ...(Array.isArray(problem.tools) ? problem.tools : []),
    problem.admission?.beneficiary,
  ].filter(Boolean).join(" ").toLowerCase();

  function missionFinding(term, value) {
    const line = node("p", "source-status");
    line.append(node("strong", "", `${term}: `), document.createTextNode(value || "Not recorded"));
    return line;
  }

  function arcCard(problem, currentIds) {
    const ready = problem.admission?.status === "ready";
    const card = node("article", `mission-card${ready ? " ready" : ""}${problem.id === requestedArcId ? " focused" : ""}`);
    card.dataset.search = arcSearchText(problem);
    card.dataset.ready = String(ready);
    card.dataset.id = problem.id;
    const stamps = node("div");
    stamps.append(statusStamp(ready ? (problem.enabled ? "Ready · enabled" : "Ready · disabled") : "Needs setup", ready ? "good" : "warn"));
    if (currentIds.has(problem.id)) stamps.append(statusStamp("Current mission", "neutral"));
    if (problem.chosen_next) stamps.append(statusStamp("Chosen next", "neutral"));
    card.append(stamps, node("h3", "", problem.title), node("p", "", problem.summary));
    card.append(missionFinding("Field", `${problem.field} / ${problem.subfield}`));
    card.append(missionFinding(
      "Source status",
      `ARC card reviewed ${problem.source_reviewed_at || "date unrecorded"}; current literature not independently checked by Discovery Loop.`,
    ));
    const details = node("details");
    details.append(node("summary", "", ready ? "Mission scope, resources, and verification" : "Source question and setup gap"));
    if (ready) {
      details.append(
        missionFinding("Beneficiary", problem.admission.beneficiary),
        missionFinding("Bounded hypothesis", problem.admission.bounded_hypothesis),
        missionFinding("Success", problem.admission.success_criterion),
        missionFinding("Resources", problem.admission.resources),
        missionFinding("Split", problem.admission.split),
        missionFinding("Baseline", problem.admission.baseline),
        missionFinding("Verifier", problem.admission.verifier),
      );
    } else {
      details.append(missionFinding("Why open", problem.why_open), missionFinding("Admission", problem.admission?.reason));
    }
    const sources = node("ul", "source-list");
    (Array.isArray(problem.sources) ? problem.sources : []).forEach((source) => {
      const item = node("li");
      const link = node("a", "", source.title);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      item.append(link);
      sources.append(item);
    });
    details.append(sources);
    card.append(details);
    const controls = node("div", "control-row");
    const atlas = node("a", "", "Open in ARC atlas");
    atlas.href = `http://127.0.0.1:3100/?problem=${encodeURIComponent(problem.id)}`;
    controls.append(atlas);
    if (ready) {
      const choose = node("button", "", problem.chosen_next ? "Chosen for next run" : "Choose for next run");
      choose.type = "button";
      choose.disabled = problem.chosen_next;
      choose.addEventListener("click", () => updateArc({ problem_id: problem.id, choose_next: true }));
      const toggle = node("button", problem.enabled ? "rust" : "", problem.enabled ? "Disable mission" : "Enable mission");
      toggle.type = "button";
      toggle.addEventListener("click", () => updateArc({ problem_id: problem.id, enabled: !problem.enabled }));
      controls.append(choose, toggle);
    }
    card.append(controls);
    return card;
  }

  function renderArc() {
    const catalogue = state.arc || {};
    const problems = Array.isArray(catalogue.problems) ? catalogue.problems : [];
    const term = byId("arc-search").value.trim().toLowerCase();
    const readyOnly = byId("arc-ready-only").checked;
    const visible = problems.filter((problem) => (!term || arcSearchText(problem).includes(term)) && (!readyOnly || problem.admission?.status === "ready"));
    const list = byId("arc-list");
    list.replaceChildren();
    const current = new Set(state.status?.night_status?.arc?.selected_missions || []);
    visible.forEach((problem) => list.append(arcCard(problem, current)));
    if (!visible.length) list.append(node("p", "empty", problems.length ? "No opportunities match this search." : "No validated catalogue snapshot is available yet."));
    const readyCount = problems.filter((problem) => problem.admission?.status === "ready").length;
    byId("arc-count").textContent = `${problems.length} sourced · ${readyCount} ready`;
    const refresh = catalogue.refresh || {};
    const source = catalogue.source || {};
    const freshness = refresh.status === "fresh" ? "Fresh local import" : refresh.status === "stale" ? "Stale import retained" : "Catalogue unavailable";
    const dirty = source.worktree_dirty ? " The source checkout contains local atlas changes beyond the recorded Git revision." : "";
    byId("arc-freshness").textContent = `${freshness}. ${problems.length} cards at revision ${String(source.revision || "unknown").slice(0, 12)}; content hash ${String(catalogue.catalogue_hash || "unknown").slice(0, 12)}.${dirty} Catalogue freshness does not establish current literature status.`;
    if (requestedArcId && !problems.some((problem) => problem.id === requestedArcId)) {
      setNotice(byId("arc-note"), "The requested ARC problem is not present in the validated local snapshot.", true);
    }
  }

  async function updateArc(payload) {
    try {
      const result = await api("/api/arc/control", { method: "POST", body: JSON.stringify(payload) });
      state.arc = result.catalogue;
      renderArc();
      setNotice(byId("arc-note"), payload.choose_next ? "Mission chosen to run first next night. If that changes the scheduled order, the night is recorded as an override." : payload.enabled ? "Mission enabled for nightly selection." : "Mission disabled; its matching research slot will be skipped next night.");
    } catch (error) { setNotice(byId("arc-note"), error.message, true); }
  }

  function evidenceLabel(item) {
    if (item.confirmed && item.publishable) return ["Confirmed", "good"];
    if (item.confirmed) return ["Confirmed · held", "warn"];
    if (["failed", "error", "rejected", "cancelled", "canceled"].includes(String(item.status).toLowerCase())) return [titleCase(item.status), "warn"];
    return ["Unvalidated", "warn"];
  }

  function addEvidenceRow(item, index) {
    const row = node("tr", "selectable");
    row.tabIndex = 0;
    row.setAttribute("aria-selected", String(state.selected === index));
    const study = node("td");
    study.append(node("span", "run-name", titleCase(item.problem)), node("br"), node("span", "subtle", `${titleCase(item.provider)} · ${item.run_id || "run"}`));
    const quality = node("td");
    const [label, kind] = evidenceLabel(item);
    quality.append(statusStamp(label, kind));
    const effect = node("td", "", formatEffect(item));
    const action = node("td");
    const button = node("button", "", "Review evidence");
    button.type = "button";
    const select = () => selectEvidence(index, true);
    button.addEventListener("click", select);
    row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
    action.append(button);
    row.append(study, quality, effect, action);
    byId("run-list").append(row);
  }

  function addLegacyRow(item) {
    const row = node("tr");
    const study = node("td");
    study.append(node("span", "run-name", titleCase(item.problem)), node("br"), node("span", "subtle", `${item.iterations} historical iterations`));
    const quality = node("td");
    quality.append(statusStamp("Unvalidated", "warn"));
    const effect = node("td", "", `${item.champions} candidate promotions`);
    const action = node("td", "subtle", `${item.wins} reported wins`);
    row.append(study, quality, effect, action);
    byId("run-list").append(row);
  }

  function renderLedger() {
    const list = byId("run-list");
    list.replaceChildren();
    state.evidence.forEach(addEvidenceRow);
    const legacy = Array.isArray(state.status.legacy) ? state.status.legacy : [];
    legacy.forEach(addLegacyRow);
    const count = state.evidence.length + legacy.length;
    byId("ledger-count").textContent = `${count} ${count === 1 ? "record" : "records"}`;
    if (!count) {
      const row = node("tr");
      const cell = node("td", "empty", "No research records yet. The next isolated run will appear here.");
      cell.colSpan = 4;
      row.append(cell);
      list.append(row);
    }
  }

  function renderTrial() {
    const trial = state.status.trial || {};
    const historical = Array.isArray(trial.rows) ? trial.rows : [];
    const clean = Array.isArray(trial.clean_rows) ? trial.clean_rows : [];
    const operational = Array.isArray(trial.operational_rows) ? trial.operational_rows : [];
    const rows = [...clean, ...operational, ...historical];
    const list = byId("trial-list");
    list.replaceChildren();
    const coverage = trial.coverage || {};
    const expected = numberFrom(coverage.expected_slots);
    const completed = numberFrom(coverage.completed_slots);
    const missing = Array.isArray(coverage.missing_slots) ? coverage.missing_slots.length : 0;
    const window = coverage.observed_date_window;
    byId("trial-count").textContent = expected ? `${completed} of ${expected} slots complete` : rows.length ? `${numberFrom(trial.runs)} scheduled runs` : "Not started";
    byId("trial-note").textContent = rows.length
      ? `${window ? `Observed ${window.start} through ${window.end}. ` : ""}${completed} completed; ${missing} configured slots not yet recorded. ${numberFrom(coverage.successful_research_calls)} successful physical research calls from ${numberFrom(coverage.attempted_research_calls)} attempts. ${coverage.partial_cycle ? "This is a partial cycle. " : "The configured cycle is complete. "}${trial.note || "Descriptive totals at the configured limits."}`
      : "The scheduled Fable, Astra, and paired comparison has not started. No provider outcome is claimed before evidence arrives.";
    if (!rows.length) {
      const row = node("tr");
      const cell = node("td", "empty", "No scheduled trial evidence yet.");
      cell.colSpan = 7;
      row.append(cell);
      list.append(row);
      return;
    }
    rows.forEach((item) => {
      const row = node("tr");
      const ratio = finite(item.confirmed_per_allowance_unit) ? numberFrom(item.confirmed_per_allowance_unit).toFixed(3) : "—";
      const failures = numberFrom(item.failed_attempts);
      const degraded = numberFrom(item.paired_degradations);
      const fallback = countText(item.fallback_reasons);
      [
        `${titleCase(item.problem)} / requested ${titleCase(item.provider)}${item.actual_strategy ? ` / ${titleCase(item.actual_strategy)}` : ""}`,
        item.provenance === "clean_formal_trial" ? "Clean formal trial" : item.provenance === "historical_unverified" ? "Historical · unverified" : "Operational · excluded",
        String(numberFrom(item.completed)) + "/" + String(numberFrom(item.runs)),
        `${countText(item.successful_model_calls)} (${shareText(item.model_call_shares)}) / all ${countText(item.actual_model_calls)}`,
        `${fallback}; ${failures} failed${degraded ? `; ${degraded} paired degraded` : ""}`,
        String(numberFrom(item.confirmed)),
        ratio,
      ].forEach((value) => row.append(node("td", "", value)));
      list.append(row);
    });
  }

  function renderHoldout() {
    const holdout = state.status.holdout || {};
    const cohort = holdout.cohort;
    const candidates = Array.isArray(holdout.candidates) ? holdout.candidates : [];
    const select = byId("holdout-candidate");
    const previousCandidate = select.value;
    select.replaceChildren();
    if (holdout.can_prepare && candidates.length) {
      candidates.forEach((candidate) => {
        const option = node("option", "", `${candidate.label} · ${String(candidate.sha256 || "").slice(0, 12)}…`);
        option.value = candidate.id;
        select.append(option);
      });
      if (candidates.some((candidate) => candidate.id === previousCandidate)) select.value = previousCandidate;
    } else if (cohort?.candidate) {
      const option = node("option", "", `${cohort.candidate.label} · ${String(cohort.candidate.sha256 || "").slice(0, 12)}…`);
      option.value = cohort.candidate.id || "";
      select.append(option);
    }
    select.disabled = !holdout.can_prepare || !candidates.length;
    byId("holdout-prepare").disabled = !holdout.can_prepare || !candidates.length;
    byId("holdout-evaluate").disabled = !holdout.can_evaluate;
    byId("holdout-boundary").textContent = holdout.notice || "Fresh synthetic CVRP cases only.";

    const stateName = String(cohort?.state || "not prepared");
    byId("holdout-state").textContent = titleCase(stateName);
    const limits = cohort?.limits || {};
    byId("holdout-cohort").textContent = cohort ? `${numberFrom(limits.case_count)} cases · ${String(cohort.instance_manifest_hash || "").slice(0, 12)}…` : "6 cases · uniform and clustered";
    byId("holdout-volume").textContent = cohort ? `${numberFrom(limits.seeds_per_case)} seeds · ${numberFrom(limits.planned_solver_runs)} solver runs` : "2 seeds · 24 solver runs";
    byId("holdout-limit").textContent = `${numberFrom(limits.solver_seconds_total, 48)} solver seconds`;
    byId("holdout-hashes").textContent = cohort
      ? `Candidate ${String(cohort.candidate?.sha256 || "").slice(0, 12)}… · baseline ${String(cohort.baseline?.sha256 || "").slice(0, 12)}… · cohort ${String(cohort.instance_manifest_hash || "").slice(0, 12)}…`
      : "Candidate, baseline, and cohort hashes appear after preparation.";
    const messages = {
      ready: "Prepared locally. Instance data and seeds remain hidden. Evaluation can run once.",
      running: "Consumed before the first solver started. Evaluation is running and cannot be retried.",
      completed: "Evaluation complete. Results below are descriptive synthetic evidence only.",
      partial: "Evaluation ended partially. The cohort is consumed; partial results are a nonclaim.",
      failed: "Evaluation failed. The cohort is consumed and no result is claimed.",
      invalid: cohort?.failure || "The seal is invalid. The cohort cannot be evaluated.",
    };
    setNotice(byId("holdout-note"), cohort ? messages[stateName] || "The cohort state needs review." : "Choose a candidate to prepare one sealed cohort.", ["partial", "failed", "invalid"].includes(stateName));

    const result = cohort?.result;
    const resultPanel = byId("holdout-results");
    resultPanel.hidden = !result;
    const list = byId("holdout-result-list");
    list.replaceChildren();
    if (!result) return;
    const rows = Array.isArray(result.rows) ? result.rows : [];
    const volumes = result.volumes || {};
    byId("holdout-result-count").textContent = `${numberFrom(volumes.matched_pairs)} of ${rows.length} matched pairs`;
    byId("holdout-result-note").textContent = `${result.classification || "Descriptive synthetic holdout."} ${numberFrom(volumes.completed_solver_runs)} of ${numberFrom(volumes.planned_solver_runs)} solver runs completed; ${numberFrom(volumes.failed_solver_runs)} failed.`;
    rows.forEach((item) => {
      const row = node("tr");
      const baseline = item.baseline?.status === "completed" ? String(item.baseline.objective) : titleCase(item.baseline?.status);
      const candidate = item.candidate?.status === "completed" ? String(item.candidate.objective) : titleCase(item.candidate?.status);
      const outcome = item.outcome === "improved"
        ? "Improved"
        : item.outcome === "worse"
          ? "Worse"
          : item.outcome === "equal_no_improvement"
            ? "Equal · no improvement"
            : "Not comparable";
      [`${titleCase(item.distribution)} · ${numberFrom(item.customers)} customers`, String(numberFrom(item.repetition)), baseline, candidate, outcome]
        .forEach((value) => row.append(node("td", "", value)));
      list.append(row);
    });
  }

  const finding = (term, content) => {
    const wrapper = node("div", "finding");
    wrapper.append(node("dt", "", term));
    const detail = node("dd");
    if (content instanceof Node) detail.append(content); else detail.textContent = content;
    wrapper.append(detail);
    return wrapper;
  };

  function confirmationText(item) {
    const confirmation = item.confirmation || {};
    const parts = [];
    const seeds = confirmation.seeds ?? confirmation.seed_count ?? (Array.isArray(confirmation.per_seed) ? confirmation.per_seed.length : null);
    if (seeds !== null && seeds !== undefined) parts.push(`${seeds} paired seeds`);
    const failures = confirmation.failures ?? confirmation.failure_count;
    if (failures !== null && failures !== undefined) parts.push(`${failures} failures`);
    if (finite(confirmation.min_effect)) parts.push(`minimum effect ${(confirmation.min_effect * 100).toFixed(1)}%`);
    return parts.length ? parts.join(" · ") : "See the raw confirmation record below.";
  }

  const shortHash = (value) => typeof value === "string" && value.length > 12 ? `${value.slice(0, 12)}…` : (value || "unknown");

  function evolutionView(item) {
    const section = node("section", "island-evolution");
    const development = item.development || item.raw?.development || {};
    const evolution = development.evolution;
    section.append(node("p", "kicker", "Program evolution"));
    const heading = node("h3", "", evolution ? "Run-local solver islands" : "Solver islands disabled");
    section.append(heading);
    if (!evolution) {
      section.append(node("p", "subtle", "This plugin used the ordinary frozen-incumbent generation path."));
      return section;
    }
    const population = evolution.population || {};
    const islands = Array.isArray(population.islands) ? population.islands : [];
    if (!islands.length) {
      section.append(node("p", "subtle", "No development-verified parent population was recorded for this run."));
      return section;
    }
    section.append(node("p", "subtle", `Three deterministic islands · up to ${population.capacity_per_island || 3} verified programs each · development evidence only.`));
    const candidates = Array.isArray(development.candidates) ? development.candidates : [];
    const byHash = new Map(candidates.filter((candidate) => candidate.candidate_hash).map((candidate) => [candidate.candidate_hash, candidate]));
    const detail = node("p", "ancestry-detail subtle", "Select a program to inspect its recorded ancestry.");
    const grid = node("div", "island-grid");
    islands.forEach((island) => {
      const card = node("section", "island-card");
      const parents = Array.isArray(island.parents) ? island.parents : [];
      const cardHead = node("div", "island-head");
      cardHead.append(node("h4", "", `Island ${Number(island.id) + 1}`), node("span", "folio", `${parents.length}/${population.capacity_per_island || 3}`));
      card.append(cardHead);
      if (!parents.length) {
        card.append(node("p", "subtle", "No verified parents yet."));
      } else {
        parents.forEach((parent) => {
          const candidate = byHash.get(parent.candidate_hash);
          const button = node("button", "parent-card");
          button.type = "button";
          button.setAttribute("aria-pressed", "false");
          button.append(
            node("strong", "", candidate?.operator || (parent.iteration === -1 ? "incumbent" : "verified program")),
            node("span", "", `Iteration ${parent.iteration ?? "unknown"} · ${parent.provider || "unknown"}`),
            node("code", "", shortHash(parent.candidate_hash)),
          );
          button.addEventListener("click", () => {
            grid.querySelectorAll(".parent-card").forEach((entry) => entry.setAttribute("aria-pressed", "false"));
            button.setAttribute("aria-pressed", "true");
            const ancestry = Array.isArray(candidate?.parent_hashes) ? candidate.parent_hashes.map(shortHash).join(" + ") : "frozen run incumbent";
            detail.textContent = `${candidate?.operator || "incumbent"} · island ${Number(candidate?.island ?? island.id) + 1} · parents ${ancestry}`;
          });
          card.append(button);
        });
      }
      grid.append(card);
    });
    section.append(grid, detail);
    if (candidates.length) {
      const ancestry = node("details", "ancestry-records");
      ancestry.append(node("summary", "", `Candidate ancestry (${candidates.length})`));
      const list = node("ul", "ancestry-list");
      candidates.slice(-12).reverse().forEach((candidate) => {
        const parents = Array.isArray(candidate.parent_hashes) ? candidate.parent_hashes.map(shortHash).join(" + ") : "not recorded";
        list.append(node("li", "", `Iteration ${candidate.iteration} · island ${Number(candidate.island) + 1} · ${candidate.operator || "unknown"} · parents ${parents}`));
      });
      ancestry.append(list);
      section.append(ancestry);
    }
    return section;
  }

  function selectEvidence(index, scroll = false) {
    state.selected = index;
    const item = state.evidence[index];
    renderLedger();
    const body = byId("evidence-body");
    body.className = "";
    body.replaceChildren();
    byId("evidence-title").textContent = titleCase(item.problem);
    byId("evidence-folio").textContent = `Run ${item.run_id || "unknown"} / ${titleCase(item.provider)}`;
    const description = item.raw?.claim || item.raw?.summary || "The candidate was evaluated against its incumbent on the recorded development and confirmation matrices.";
    const metric = node("span");
    metric.append(node("span", "metric", formatEffect(item)), node("br"), node("span", "subtle", confirmationText(item)));
    const limits = Array.isArray(item.limitations) ? item.limitations.join(" ") : (item.limitations || "No limitations were recorded. Treat the claim as bounded by the listed benchmark and confirmation split.");
    const candidate = node("span");
    candidate.append(node("code", "", item.candidate_path || "No candidate path recorded"));
    if (item.candidate_hash) candidate.append(node("br"), node("span", "subtle", `SHA-256 · ${item.candidate_hash.slice(0, 12)}…${item.candidate_hash.slice(-8)}`));
    const routing = item.routing || {};
    const routingText = routing.provenance === "historical_unverified"
      ? "Historical routing provenance is unverified."
      : `${routing.formal_trial_eligible ? "Clean formal routing" : "Operational routing excluded from clean ratios"} · models ${countText(routing.actual_model_calls)} · families ${countText(routing.actual_family_calls)}${Object.keys(routing.failure_reasons || {}).length ? ` · failures ${countText(routing.failure_reasons)}` : ""}`;
    const dl = node("dl");
    dl.append(finding("Claim", description));
    if (item.raw?.mission) {
      const mission = item.raw.mission;
      dl.append(finding("Mission", `${mission.source_title || mission.source_problem_id}. ${mission.beneficiary || ""}`));
      dl.append(finding("Mission success", mission.success_criterion || "See the bound mission record."));
    }
    dl.append(finding("Confirmation", metric), finding("Routing", routingText), finding("Limits", limits), finding("Candidate", candidate));
    const details = node("details");
    details.append(node("summary", "", "Technical evidence and raw record"));
    const pre = node("pre");
    pre.textContent = JSON.stringify(item.raw, null, 2);
    details.append(pre);
    body.append(dl, evolutionView(item), details);
    const panel = byId("approval-panel");
    panel.hidden = false;
    const eligible = item.confirmed && item.publishable && item.candidate_path && item.candidate_hash;
    byId("approval-check").checked = false;
    byId("approval-check").disabled = !eligible;
    byId("approve").disabled = true;
    byId("request-review").disabled = false;
    const marked = state.status.control?.review_request?.evidence_path === item.evidence_path;
    setNotice(byId("approval-note"), marked ? "Marked for your morning review. This does not run a model." : eligible ? "" : "This evidence is not eligible for release approval.", !marked && !eligible);
    if (scroll) document.querySelector(".evidence").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function populateSchedule() {
    const schedule = state.status.schedule || {};
    const caps = schedule.provider_caps_usd || {};
    byId("budget").value = schedule.nightly_budget_usd ?? 90;
    byId("minutes").value = schedule.duration_minutes ?? 480;
    byId("cap-fable").value = caps.fable ?? 20;
    byId("cap-astra").value = caps.astra ?? 20;
    byId("cap-paired").value = caps.paired ?? 20;
    const routing = schedule.routing || {};
    byId("routing-policy").value = routing.policy || "scheduled";
    byId("routing-chain").value = Array.isArray(routing.chain) ? routing.chain.join(", ") : "fable, opus, astra, sol";
    const disabled = Array.isArray(routing.disabled_families) ? routing.disabled_families : [];
    byId("disable-anthropic").checked = disabled.includes("anthropic");
    byId("disable-openai").checked = disabled.includes("openai");
  }

  async function load() {
    try {
      const status = await api("/api/status");
      state.status = status;
      state.csrf = status.csrf_token;
      const [evidence, catalogue] = await Promise.all([api("/api/evidence"), api("/api/arc/catalogue")]);
      state.evidence = Array.isArray(evidence.evidence) ? evidence.evidence : [];
      state.arc = catalogue;
      if (requestedArcId) byId("arc-ready-only").checked = false;
      renderNight();
      renderArc();
      populateSchedule();
      renderTrial();
      renderHoldout();
      if (state.evidence.length) selectEvidence(0); else renderLedger();
      document.body.classList.add("loaded");
      if (requestedArcId) document.querySelector(`[data-id="${requestedArcId}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (error) {
      byId("run-list").innerHTML = "";
      const row = node("tr");
      const cell = node("td", "empty", error.message);
      cell.colSpan = 4;
      row.append(cell);
      byId("run-list").append(row);
      setNotice(byId("control-note"), "The local dashboard could not read its state.", true);
    }
  }

  async function control(action, evidencePath) {
    const payload = { action };
    if (evidencePath) payload.evidence_path = evidencePath;
    const target = action === "request_review" ? byId("approval-note") : byId("control-note");
    try {
      const result = await api("/api/control", { method: "POST", body: JSON.stringify(payload) });
      state.status.control = result.control;
      renderNight();
      const message = action === "pause" ? "Pause requested for the next checkpoint." : action === "continue" ? "Research can continue at the next checkpoint." : "Marked for your morning review. This does not run a model.";
      setNotice(target, message);
    } catch (error) { setNotice(target, error.message, true); }
  }

  byId("pause").addEventListener("click", () => control("pause"));
  byId("continue").addEventListener("click", () => control("continue"));
  byId("holdout-prepare").addEventListener("click", async () => {
    const button = byId("holdout-prepare");
    button.disabled = true;
    try {
      const result = await api("/api/holdout/prepare", { method: "POST", body: JSON.stringify({ candidate_id: byId("holdout-candidate").value }) });
      state.status.holdout = result.holdout;
      renderHoldout();
    } catch (error) {
      setNotice(byId("holdout-note"), error.message, true);
      button.disabled = false;
    }
  });
  byId("holdout-evaluate").addEventListener("click", async () => {
    const button = byId("holdout-evaluate");
    button.disabled = true;
    setNotice(byId("holdout-note"), "Cohort is being consumed before the first isolated solver starts…");
    try {
      const result = await api("/api/holdout/evaluate", { method: "POST", body: "{}" });
      state.status.holdout = result.holdout;
      renderHoldout();
    } catch (error) {
      setNotice(byId("holdout-note"), error.message, true);
    }
  });
  byId("arc-search").addEventListener("input", renderArc);
  byId("arc-ready-only").addEventListener("change", renderArc);
  byId("approval-check").addEventListener("change", () => {
    const item = state.evidence[state.selected];
    byId("approve").disabled = !byId("approval-check").checked || !item?.confirmed || !item?.publishable;
  });
  byId("request-review").addEventListener("click", () => {
    const item = state.evidence[state.selected];
    if (item) control("request_review", item.evidence_path);
  });
  byId("schedule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      duration_minutes: Number(byId("minutes").value),
      nightly_budget_usd: Number(byId("budget").value),
      provider_caps_usd: {
        fable: Number(byId("cap-fable").value),
        astra: Number(byId("cap-astra").value),
        paired: Number(byId("cap-paired").value),
      },
      routing: {
        policy: byId("routing-policy").value,
        chain: byId("routing-chain").value.split(",").map((value) => value.trim()).filter(Boolean),
        disabled_families: [
          ...(byId("disable-anthropic").checked ? ["anthropic"] : []),
          ...(byId("disable-openai").checked ? ["openai"] : []),
        ],
      },
    };
    try {
      const result = await api("/api/schedule", { method: "POST", body: JSON.stringify(payload) });
      state.status.schedule = result.schedule;
      populateSchedule();
      setNotice(byId("save-note"), "Next-night limits saved locally.");
    } catch (error) { setNotice(byId("save-note"), error.message, true); }
  });
  byId("approve").addEventListener("click", async () => {
    const item = state.evidence[state.selected];
    if (!item || !byId("approval-check").checked) return;
    byId("approve").disabled = true;
    const payload = {
      evidence_path: item.evidence_path,
      evidence_hash: item.evidence_hash,
      candidate_path: item.candidate_path,
      candidate_hash: item.candidate_hash,
      confirmed: true,
    };
    try {
      const result = await api("/api/approve", { method: "POST", body: JSON.stringify(payload) });
      byId("approval-check").disabled = true;
      setNotice(byId("approval-note"), result.message);
    } catch (error) {
      byId("approval-check").checked = false;
      byId("approval-check").disabled = false;
      setNotice(byId("approval-note"), error.message, true);
    }
  });

  load();
})();
