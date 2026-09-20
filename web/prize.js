(() => {
  "use strict";

  const state = { csrf: "", data: null };
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
  const titleCase = (value) => String(value || "unknown").replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const money = (value) => {
    if (!finite(value)) return "—";
    if (value !== 0 && Math.abs(value) < 1) return "under $1";
    if (Math.abs(value) >= 1e6) return `$${value.toExponential(2)}`;
    return `$${Math.round(value).toLocaleString("en-US")}`;
  };
  const pct = (value) => (finite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(2)}%` : "—");
  const count = (value) => (finite(value) ? String(value) : "0");
  const stamp = (label, kind) => {
    const span = node("span", `stamp ${kind}`, label);
    span.prepend(node("span", "signal"));
    return span;
  };
  const statusKind = (status) => {
    if (status === "verified_active") return "good";
    if (["closed", "solved", "not_prize_eligible", "historical"].includes(status)) return "neutral";
    return "warn";
  };
  const stateKind = (value) => {
    if (["ready-for-review", "progressing"].includes(value)) return "good";
    if (["stalled", "ready-for-confirmation"].includes(value)) return "warn";
    return "neutral";
  };
  const fact = (term, value) => {
    const wrapper = node("div");
    wrapper.append(node("dt", "", term), node("dd", "", value === undefined || value === null || value === "" ? "Not recorded" : String(value)));
    return wrapper;
  };
  const field = (labelText, control) => {
    const wrapper = node("label", "field");
    wrapper.append(node("span", "", labelText), control);
    return wrapper;
  };
  const select = (options, value) => {
    const element = document.createElement("select");
    options.forEach((option) => {
      const item = document.createElement("option");
      item.value = option;
      item.textContent = titleCase(option);
      element.append(item);
    });
    if (value) element.value = value;
    return element;
  };
  const input = (placeholder) => {
    const element = document.createElement("input");
    element.type = "text";
    element.placeholder = placeholder;
    return element;
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

  async function post(path, payload, message) {
    const notice = byId("prize-notice");
    setNotice(notice, "Writing…");
    try {
      const result = await api(path, { method: "POST", body: JSON.stringify(payload) });
      state.data = result.prize;
      renderAll();
      setNotice(byId("prize-notice"), message);
    } catch (error) {
      setNotice(byId("prize-notice"), error.message, true);
    }
  }

  function renderMasthead(data) {
    const registry = data.registry || {};
    const refresh = registry.refresh || {};
    const board = data.board || [];
    const ready = board.filter((row) => row.admission === "ready").length;
    const stampNode = byId("prize-stamp");
    stampNode.className = `stamp ${refresh.status === "fresh" ? "good" : "neutral"}`;
    stampNode.replaceChildren(node("span", "signal"), document.createTextNode(`Registry ${titleCase(refresh.status || "uncached")}`));
    byId("prize-summary").textContent = `${board.length} prizes on record · ${ready} runnable here · ${board.filter((row) => row.enabled).length} enabled`;
    byId("lede-count").textContent = board.length === 1 ? "One public challenge" : `${board.length} public challenges`;
    const source = registry.source || {};
    byId("prize-source").textContent = source.updated_at
      ? `data/prizes.json last edited ${source.updated_at}; amounts are quoted from public pages and are untrusted display data.`
      : "Prize wording and amounts are quoted from public pages and are untrusted display data.";
    const notices = Array.isArray(data.notices) ? data.notices : [];
    if (notices.length) setNotice(byId("prize-notice"), notices.join(" "));
  }

  function renderMoneyBoard(data) {
    const list = byId("money-board");
    const money_board = data.money_board || {};
    const keys = Object.keys(money_board);
    byId("money-folio").textContent = `${keys.filter((key) => money_board[key] && money_board[key].id).length} of ${keys.length} answered`;
    if (!keys.length) {
      list.replaceChildren(node("p", "empty", "No prize registry is present in this checkout."));
      return;
    }
    const cards = keys.map((key) => {
      const pick = money_board[key] || {};
      const card = node("article", "card");
      card.append(node("p", "kicker", titleCase(key)));
      card.append(node("h3", "", pick.name || "No prize matches this rule"));
      card.append(node("p", "rail-copy", pick.rule || ""));
      const facts = node("dl", "card-facts");
      facts.append(fact("Why", pick.why));
      facts.append(fact("Registry id", pick.id));
      card.append(facts);
      return card;
    });
    list.replaceChildren(...cards);
  }

  function scalingText(scaling) {
    if (!scaling) return "No plugin bound";
    if (!scaling.supported) return `Not fitted: ${scaling.reason || "no ladder points"}`;
    return `${titleCase(scaling.verdict)} at ${scaling.target_bits} bits — ${scaling.summary}`;
  }

  function renderBoard(data) {
    const list = byId("board-list");
    const board = data.board || [];
    byId("board-folio").textContent = `${board.length} prizes`;
    if (!board.length) {
      const row = node("tr");
      const cell = node("td", "empty", "No prize registry is present in this checkout.");
      cell.colSpan = 9;
      row.append(cell);
      list.replaceChildren(row);
      return;
    }
    const rows = board.map((item) => {
      const tr = node("tr");
      const first = node("td");
      first.append(node("strong", "", item.name));
      first.append(node("p", "subtle", `${titleCase(item.category)} · ${item.advertised_prize || "no advertised amount"}`));
      first.append(stamp(titleCase(item.research_state), stateKind(item.research_state)));
      if (item.chosen_next) first.append(stamp("Chosen next", "good"));
      tr.append(first);

      const statusCell = node("td");
      statusCell.append(stamp(titleCase(item.status), statusKind(item.status)));
      statusCell.append(node("p", "subtle", `${titleCase(item.status_confidence)} confidence · checked ${item.last_verified || "never"}`));
      tr.append(statusCell);

      const score = item.score || {};
      const cash = score.cash_ev_usd || {};
      const credibility = score.credibility_ev_usd || {};
      const ev = node("td");
      ev.append(node("span", "", titleCase(score.bucket || "unscored")));
      ev.append(node("p", "subtle", `cash ${money(cash.mid)} · credibility ${money(credibility.mid)}`));
      tr.append(ev);

      const cost = score.cost_usd || {};
      const costCell = node("td", "", money(cost.mid));
      costCell.append(node("p", "subtle", `range ${money(cost.low)} to ${money(cost.high)}`));
      tr.append(costCell);

      const best = item.best_candidate;
      const bestCell = node("td");
      if (best) {
        bestCell.append(node("span", "", `${best.run_id} · iteration ${best.iteration}`));
        bestCell.append(node("p", "subtle", best.idea || ""));
      } else {
        bestCell.append(node("span", "", "No candidate on record"));
      }
      tr.append(bestCell);

      tr.append(node("td", finite(item.performance_improvement_pct) && item.performance_improvement_pct > 0 ? "gain-up" : "", pct(item.performance_improvement_pct)));
      tr.append(node("td", "", scalingText(item.scaling)));

      const spend = item.research_spend || {};
      const spendCell = node("td", "", money(spend.model_usd));
      spendCell.append(node("p", "subtle", `${count(item.attempts)} attempts · electricity ${money(spend.local_compute_usd)} · ${count(item.dead_ends)} dead ends`));
      tr.append(spendCell);

      tr.append(node("td", "idea", item.next_experiment || "Not recorded"));
      return tr;
    });
    list.replaceChildren(...rows);
  }

  function renderStatusForms(data) {
    const holder = byId("status-forms");
    const board = data.board || [];
    if (!board.length) {
      holder.replaceChildren(node("p", "empty", "No prize registry is present in this checkout."));
      return;
    }
    const statuses = ["verified_active", "probably_active", "status_uncertain", "historical", "closed", "solved", "not_prize_eligible"];
    const forms = board.map((item) => {
      const details = document.createElement("details");
      details.append(node("summary", "", `${item.name} — ${titleCase(item.status)} (${titleCase(item.status_confidence)})`));
      const status = select(statuses, item.status);
      const confidence = select(["high", "medium", "low"], item.status_confidence);
      const observed = input("What did you see on the page?");
      const url = input("https://…");
      details.append(field("Status", status), field("Confidence", confidence), field("Observed", observed), field("Source URL", url));
      const button = node("button", "primary", "Record this status check");
      button.type = "button";
      button.addEventListener("click", () => post(
        "/api/prizes/status",
        {
          prize_id: item.id,
          status: status.value,
          status_confidence: confidence.value,
          observed: observed.value,
          url: url.value,
        },
        `Recorded a status check for ${item.name}.`,
      ));
      const row = node("div", "control-row");
      row.append(button);
      details.append(row);
      return details;
    });
    holder.replaceChildren(...forms);
  }

  function renderQueue(data) {
    const queue = data.queue || {};
    const list = byId("queue-list");
    const allocations = queue.allocations || [];
    byId("queue-folio").textContent = `${allocations.length} of ${money(queue.allowance_usd)} planned`;
    const nightly = data.nightly || {};
    byId("nightly-state").textContent = `Nightly Prize Hunt: ${nightly.enabled ? "enabled" : "disabled"}. This plan splits ${money(queue.allowance_usd)} over ${count(queue.minutes)} minutes from the ${queue.source} (${queue.label}); ${money(queue.unallocated_usd)} stayed unallocated.`;
    if (!allocations.length) {
      const row = node("tr");
      const cell = node("td", "empty", (queue.notes || []).join(" ") || "Nothing is planned for this allowance.");
      cell.colSpan = 6;
      row.append(cell);
      list.replaceChildren(row);
      return;
    }
    const rows = allocations.map((item) => {
      const tr = node("tr");
      tr.append(node("td", "", item.prize_id));
      tr.append(node("td", "", item.plugin || "—"));
      tr.append(node("td", "", titleCase(item.bucket)));
      tr.append(node("td", "", money(item.usd)));
      tr.append(node("td", "", count(item.minutes)));
      tr.append(node("td", "idea", item.reason));
      return tr;
    });
    list.replaceChildren(...rows);
  }

  function renderControls(data) {
    const holder = byId("prize-controls");
    const board = (data.board || []).filter((row) => row.admission === "ready");
    if (!board.length) {
      holder.replaceChildren(node("p", "empty", "No prize in this registry has a reviewed binding to an installed plugin."));
      return;
    }
    const cards = board.map((item) => {
      const card = node("article", "card");
      card.append(node("p", "kicker", item.plugin || "no plugin"));
      card.append(node("h3", "", item.name));
      card.append(node("p", "rail-copy", item.enabled ? "Enabled: eligible for the nightly plan." : "Disabled: excluded from the nightly plan."));
      const row = node("div", "control-row");
      const toggle = node("button", item.enabled ? "rust" : "primary", item.enabled ? "Disable" : "Enable");
      toggle.type = "button";
      toggle.addEventListener("click", () => post(
        "/api/prizes/control",
        { action: item.enabled ? "disable" : "enable", prize_id: item.id },
        `${item.enabled ? "Disabled" : "Enabled"} ${item.name}.`,
      ));
      row.append(toggle);
      const choose = node("button", "", item.chosen_next ? "Clear next choice" : "Choose next");
      choose.type = "button";
      choose.addEventListener("click", () => post(
        "/api/prizes/control",
        item.chosen_next ? { action: "clear_next" } : { action: "choose_next", prize_id: item.id },
        item.chosen_next ? "Cleared the next-run choice." : `${item.name} will be picked up next.`,
      ));
      row.append(choose);
      card.append(row);
      return card;
    });
    holder.replaceChildren(...cards);
  }

  function renderEconomics(data) {
    const holder = byId("direction-list");
    const economics = data.economics || {};
    const directions = [];
    let total = 0;
    Object.keys(economics).forEach((plugin) => {
      total += economics[plugin].directions_total || 0;
      (economics[plugin].directions || []).forEach((direction) => directions.push({ plugin, ...direction }));
    });
    const totals = Object.keys(economics).reduce((sum, plugin) => sum + ((economics[plugin].totals || {}).model_usd || 0), 0);
    byId("economics-folio").textContent = `${directions.length} of ${total} directions · ${money(totals)} charged`;
    if (!directions.length) {
      holder.replaceChildren(node("p", "empty", "No research run has been recorded for a prize plugin yet."));
      return;
    }
    const cards = directions.map((direction) => {
      const card = node("article", "card");
      card.append(node("p", "kicker", `${direction.plugin} · ${titleCase(direction.verdict)}`));
      card.append(node("h3", "", direction.family));
      card.append(node("p", "rail-copy", direction.sentence));
      const facts = node("dl", "card-facts");
      facts.append(fact("Attempts", direction.attempts));
      facts.append(fact("Best gain", finite(direction.best_gain) ? pct(direction.best_gain * 100) : "none measured"));
      facts.append(fact("Cost", money(direction.total_cost_usd)));
      card.append(facts);
      return card;
    });
    holder.replaceChildren(...cards);
  }

  function renderStops(data) {
    const holder = byId("stop-list");
    const stops = data.stop_recommendations || [];
    if (!stops.length) {
      holder.replaceChildren(node("p", "empty", "No direction has spent enough with no measured gain to be proposed as a dead end."));
      return;
    }
    const cards = stops.map((stop) => {
      const card = node("article", "card");
      card.append(node("p", "kicker", stop.problem || "general"));
      card.append(node("h3", "", stop.approach));
      card.append(node("p", "rail-copy", stop.why_failed));
      card.append(node("p", "subtle", stop.evidence));
      const row = node("div", "control-row");
      const button = node("button", "rust", "Record as dead end");
      button.type = "button";
      button.addEventListener("click", () => post(
        "/api/prizes/dead-end",
        {
          approach: stop.approach,
          why_failed: stop.why_failed,
          evidence: stop.evidence,
          tags: stop.tags || [],
          problem: stop.problem || "general",
        },
        "Recorded the dead end in problems/_dead_ends.json.",
      ));
      row.append(button);
      card.append(row);
      return card;
    });
    holder.replaceChildren(...cards);
  }

  function renderReady(data) {
    const holder = byId("ready-list");
    const board = (data.board || []).filter((row) => row.ready_for_confirmation || row.ready_for_human_review);
    byId("ready-folio").textContent = `${board.length} waiting`;
    if (!board.length) {
      holder.replaceChildren(node("p", "empty", "Nothing is waiting on a person: no candidate has cleared the minimum effect and no confirmation is unread."));
      return;
    }
    const cards = board.map((item) => {
      const card = node("article", "card");
      card.append(node("p", "kicker", item.ready_for_human_review ? "Confirmed evidence is unread" : "A candidate is waiting for confirmation"));
      card.append(node("h3", "", item.name));
      const facts = node("dl", "card-facts");
      facts.append(fact("Plugin", item.plugin));
      facts.append(fact("Improvement", pct(item.performance_improvement_pct)));
      facts.append(fact("Best candidate", item.best_candidate ? `${item.best_candidate.run_id} · iteration ${item.best_candidate.iteration}` : "none"));
      facts.append(fact("Next experiment", item.next_experiment));
      card.append(facts);
      card.append(node("p", "next-step", item.ready_for_human_review ? "Open the review dashboard to read the evidence." : "Run a confirmation before treating this as a result."));
      return card;
    });
    holder.replaceChildren(...cards);
  }

  function renderIntake(data) {
    const holder = byId("intake-list");
    const intake = data.intake || [];
    byId("intake-folio").textContent = `${intake.length} candidates`;
    if (!intake.length) {
      holder.replaceChildren(node("p", "empty", "No intake candidate is waiting. Add one with python prize_intake.py add <url>."));
      return;
    }
    const cards = intake.map((item) => {
      const card = node("article", "card");
      card.append(node("p", "kicker", `${titleCase(item.kind)} · ${titleCase(item.status)}`));
      card.append(node("h3", "", item.title || item.slug));
      card.append(node("p", "subtle", item.url || ""));
      const facts = node("dl", "card-facts");
      facts.append(fact("Fetched", item.fetched_at));
      facts.append(fact("File", item.path));
      card.append(facts);
      if (item.status === "candidate") {
        const reason = input("Why reject it?");
        card.append(field("Reject reason", reason));
        const row = node("div", "control-row");
        const approve = node("button", "primary", "Approve");
        approve.type = "button";
        approve.addEventListener("click", () => post("/api/prizes/intake", { action: "approve", slug: item.slug }, `Approved ${item.slug} into the registry.`));
        const rejectButton = node("button", "rust", "Reject");
        rejectButton.type = "button";
        rejectButton.addEventListener("click", () => post("/api/prizes/intake", { action: "reject", slug: item.slug, reason: reason.value }, `Rejected ${item.slug}.`));
        row.append(approve, rejectButton);
        card.append(row);
      }
      return card;
    });
    holder.replaceChildren(...cards);
  }

  function renderFootnote(data) {
    const list = byId("non-claims");
    const claims = data.non_claims || [];
    list.replaceChildren(...claims.map((claim) => node("li", "", `${claim.plugin} (${claim.source}): ${claim.sentence}`)));
  }

  function renderAll() {
    const data = state.data || {};
    renderMasthead(data);
    renderMoneyBoard(data);
    renderBoard(data);
    renderStatusForms(data);
    renderQueue(data);
    renderControls(data);
    renderEconomics(data);
    renderStops(data);
    renderReady(data);
    renderIntake(data);
    renderFootnote(data);
  }

  async function load() {
    try {
      const status = await api("/api/status");
      state.csrf = status.csrf_token || "";
      state.data = await api("/api/prizes");
    } catch (error) {
      byId("prize-summary").textContent = `Could not read the prize board: ${error.message}`;
      return;
    }
    renderAll();
    document.body.classList.add("loaded");
  }

  load();
})();
