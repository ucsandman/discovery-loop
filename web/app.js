(() => {
  "use strict";

  const state = { csrf: "", status: null, evidence: [], selected: null };
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
    const date = value ? new Date(value) : new Date();
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
    const iterations = slots.reduce((sum, slot) => sum + numberFrom(slot.night_iterations ?? slot.iterations), 0);
    const spend = slots.reduce((sum, slot) => sum + numberFrom(slot.night_spend_usd ?? slot.spent_usd), 0);
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
    const usageParts = [`${iterations} iterations`, `${formatAllowance(spend)} reported total_cost_usd API-equivalent`];
    if (tokens) usageParts.push(`${new Intl.NumberFormat().format(tokens)} tokens`);
    byId("night-usage").textContent = slots.length ? usageParts.join(" · ") : "Historical results remain available below.";
    byId("dateline").textContent = dateText(night.started || night.started_at || status.generated_at);
    byId("pause").disabled = control.paused === true;
    byId("continue").disabled = control.paused !== true;
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
    const rows = Array.isArray(trial.rows) ? trial.rows : [];
    const list = byId("trial-list");
    list.replaceChildren();
    byId("trial-count").textContent = rows.length ? `${numberFrom(trial.runs)} scheduled runs` : "Not started";
    byId("trial-note").textContent = rows.length
      ? (trial.note || "Descriptive totals at the configured limits.")
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
      [
        `${titleCase(item.problem)} / ${titleCase(item.provider)}`,
        String(numberFrom(item.completed)) + "/" + String(numberFrom(item.runs)),
        String(numberFrom(item.confirmed)),
        String(numberFrom(item.calls)),
        numberFrom(item.allowance_charged).toFixed(2),
        numberFrom(item.solver_hours).toFixed(2),
        ratio,
      ].forEach((value) => row.append(node("td", "", value)));
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
    const dl = node("dl");
    dl.append(finding("Claim", description), finding("Confirmation", metric), finding("Limits", limits), finding("Candidate", candidate));
    const details = node("details");
    details.append(node("summary", "", "Technical evidence and raw record"));
    const pre = node("pre");
    pre.textContent = JSON.stringify(item.raw, null, 2);
    details.append(pre);
    body.append(dl, details);
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
  }

  async function load() {
    try {
      const status = await api("/api/status");
      state.status = status;
      state.csrf = status.csrf_token;
      const evidence = await api("/api/evidence");
      state.evidence = Array.isArray(evidence.evidence) ? evidence.evidence : [];
      renderNight();
      populateSchedule();
      renderTrial();
      if (state.evidence.length) selectEvidence(0); else renderLedger();
      document.body.classList.add("loaded");
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
