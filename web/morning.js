(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const titleCase = (value) => String(value || "unknown").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const pct = (value) => {
    if (!finite(value)) return "—";
    const percent = value * 100;
    const digits = Math.abs(percent) < 0.1 ? 3 : 2;
    return `${percent > 0 ? "+" : ""}${percent.toFixed(digits)}%`;
  };
  const allowance = (value) => (finite(value) ? value.toFixed(2) : "—");
  const clock = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
  };
  const longDate = (value) => {
    const dateOnly = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
    const date = dateOnly ? new Date(...value.split("-").map((part, index) => Number(part) - (index === 1 ? 1 : 0))) : new Date(value || Date.now());
    return Number.isNaN(date.valueOf()) ? "" : new Intl.DateTimeFormat(undefined, { weekday: "long", day: "2-digit", month: "long", year: "numeric" }).format(date);
  };
  const countText = (value) => Object.entries(value && typeof value === "object" ? value : {})
    .map(([name, count]) => `${name} ${count}`).join(" · ") || "—";
  const stamp = (label, kind) => {
    const span = node("span", `stamp ${kind}`, label);
    return span;
  };
  const statusKind = (status) => {
    if (status === "completed") return "good";
    if (["failed", "error", "timed_out", "provider_unavailable"].includes(status)) return "warn";
    return "neutral";
  };
  const fact = (term, value) => {
    const wrapper = node("div");
    wrapper.append(node("dt", "", term), node("dd", "", value === undefined || value === null || value === "" ? "Not recorded" : String(value)));
    return wrapper;
  };

  function renderMasthead(brief) {
    const night = brief.last_night;
    const stampNode = byId("night-stamp");
    if (!night) {
      byId("night-summary").textContent = "No research night on record";
      byId("dateline").textContent = "Morning brief";
      return;
    }
    const totals = night.totals || {};
    const kind = statusKind(night.status);
    stampNode.className = `stamp ${kind}`;
    stampNode.replaceChildren(node("span", "signal"), document.createTextNode(titleCase(night.status)));
    byId("dateline").textContent = `Morning brief · ${longDate(night.date)}`;
    byId("night-summary").textContent = `${totals.completed ?? 0} of ${totals.slots ?? 0} slots finished · ${totals.candidates ?? 0} ideas tried · ${totals.confirmed ?? 0} confirmed`;
    byId("night-usage").textContent = `${allowance(night.budget_used)} of ${allowance(night.budget_limit)} allowance · started ${clock(night.started_at)}, last write ${clock(night.finished_at)}`;
  }

  function renderAwaiting(items) {
    const list = byId("awaiting-list");
    list.replaceChildren();
    byId("awaiting-count").textContent = `${items.length} ${items.length === 1 ? "item" : "items"}`;
    if (!items.length) {
      list.append(node("p", "empty", "Nothing is waiting on you. Every confirmed result in the history is either not publishable or already handled."));
      return;
    }
    const labels = {
      publishable_unapproved: ["Publishable, not approved", "warn"],
      approved_not_released: ["Approved, not pushed", "warn"],
      record_beat_unsubmitted: ["Beats stored record, not submitted", "warn"],
    };
    items.forEach((item) => {
      const card = node("article", "card awaiting");
      const [label, kind] = labels[item.kind] || [titleCase(item.kind), "neutral"];
      card.append(stamp(label, kind));
      card.append(node("h3", "", `${titleCase(item.problem)}${item.target ? ` · ${item.target}` : ""}`));
      const facts = node("dl", "card-facts");
      if (item.date) facts.append(fact("Night", item.date));
      if (finite(item.value)) facts.append(fact("Stored result", `${item.value} vs record ${item.record}`));
      if (item.claim_type) facts.append(fact("Claim", titleCase(item.claim_type)));
      facts.append(fact("Evidence", item.evidence_path));
      card.append(facts);
      card.append(node("p", "subtle", item.detail));
      card.append(node("p", "next-step", `Next: ${item.next_step}`));
      list.append(card);
    });
  }

  function candidateRows(slot) {
    const wrap = node("div", "table-wrap trial-table-wrap");
    const table = node("table");
    const head = node("thead");
    const headRow = node("tr");
    ["Iter", "Model", "Idea", "Median gain", "Bound (10%)", "Seeds", "Outcome"].forEach((label) => headRow.append(node("th", "", label)));
    head.append(headRow);
    const body = node("tbody");
    const rows = [...slot.candidates].sort((a, b) => (b.median_gain ?? -Infinity) - (a.median_gain ?? -Infinity));
    rows.forEach((row) => {
      const tr = node("tr");
      tr.append(node("td", "", row.iteration ?? "—"));
      tr.append(node("td", "", row.model || row.arm || "—"));
      tr.append(node("td", "idea", row.idea || "(no idea recorded)"));
      const gain = node("td", finite(row.median_gain) && row.median_gain > 0 ? "gain-up" : "", pct(row.median_gain));
      tr.append(gain);
      // A median without its bound and its seed count reads as a result; the gate needs all three.
      tr.append(node("td", finite(row.median_lower_bound) && row.median_lower_bound > 0 ? "gain-up" : "", pct(row.median_lower_bound)));
      tr.append(node("td", "", finite(row.seeds) ? String(row.seeds) : "-"));
      tr.append(node("td", "", titleCase(row.status)));
      body.append(tr);
    });
    table.append(head, body);
    wrap.append(table);
    return wrap;
  }

  function renderSlot(slot) {
    const card = node("article", "slot-card");
    const head = node("div", "slot-head");
    const title = node("div");
    title.append(node("p", "kicker", `${titleCase(slot.problem)} · ${slot.arm ? `${slot.arm} arm` : titleCase(slot.kind)}`));
    title.append(node("h3", "", slot.mission?.title || titleCase(slot.problem)));
    head.append(title);
    const stamps = node("div", "stamp-row");
    stamps.append(stamp(titleCase(slot.status), statusKind(slot.status)));
    if (slot.kind === "research" && slot.status === "completed") {
      stamps.append(stamp(slot.confirmed ? "Confirmed" : "Not confirmed", slot.confirmed ? "good" : "neutral"));
      stamps.append(stamp(slot.publishable ? "Publishable" : "Not publishable", slot.publishable ? "good" : "neutral"));
    }
    head.append(stamps);
    card.append(head);
    if (slot.reason) card.append(node("p", "subtle", `Skipped: ${titleCase(slot.reason)}`));

    const grid = node("div", "slot-grid");
    const problem = node("section");
    problem.append(node("h4", "", "Problem we are trying to solve"));
    const mission = node("dl", "card-facts");
    mission.append(fact("Hypothesis", slot.mission?.hypothesis));
    mission.append(fact("Success looks like", slot.mission?.success_criterion));
    if (slot.mission?.beneficiary) mission.append(fact("Who benefits", slot.mission.beneficiary));
    problem.append(mission);
    grid.append(problem);

    const worked = node("section");
    worked.append(node("h4", "", "What worked"));
    const facts = node("dl", "card-facts");
    if (slot.best) {
      facts.append(fact("Best idea", `${slot.best.idea} (${pct(slot.best.median_gain)} median, ${titleCase(slot.best.status)})`));
    } else if (slot.kind === "research") {
      facts.append(fact("Best idea", "No valid candidate produced a score"));
    }
    if (slot.confirmation) {
      const c = slot.confirmation;
      facts.append(fact("Confirmation", `${c.wins} wins, ${c.losses} losses over ${c.pairs} matched pairs; mean gain ${pct(c.mean_gain)}${c.candidate_failures ? `; ${c.candidate_failures} candidate failures` : ""}`));
    }
    if (slot.release_checks) {
      const r = slot.release_checks;
      facts.append(fact("Release validation", `${r.passed} of ${r.checked} passed${r.first_error ? ` — ${r.first_error}` : ""}`));
    }
    if (slot.publishable_reason) facts.append(fact("Publishable?", slot.publishable_reason));
    if (slot.retro?.verdict) facts.append(fact("Analyst verdict", slot.retro.verdict));
    if (slot.generation_stop?.reason) facts.append(fact("Generation stopped", titleCase(slot.generation_stop.reason)));
    facts.append(fact("Model calls", `${slot.calls ?? 0} calls · ${allowance(slot.charged)} allowance · ${countText(slot.by_model)}`));
    worked.append(facts);
    grid.append(worked);
    card.append(grid);

    if (slot.candidates?.length) {
      const details = node("details", "tried");
      const summary = node("summary", "", `What was tried: ${slot.candidates.length} ideas, ${slot.promising} promising`);
      details.append(summary, candidateRows(slot));
      details.open = true;
      card.append(details);
    }
    if (slot.retro?.excerpt) {
      const details = node("details");
      details.append(node("summary", "", `Retrospective (${slot.retro.model || slot.retro.arm || "analyst"})`));
      details.append(node("pre", "retro", slot.retro.excerpt));
      card.append(details);
    }
    return card;
  }

  function renderNight(brief) {
    const night = brief.last_night;
    const list = byId("slot-list");
    list.replaceChildren();
    if (!night) {
      byId("night-folio").textContent = "No record";
      list.append(node("p", "empty", "No night.json under runs/research yet."));
      return;
    }
    byId("night-folio").textContent = night.run_id;
    const notes = [];
    if (night.trial_assignment) notes.push(`Trial night ${(night.trial_index ?? 0) + 1}: ${Object.entries(night.trial_assignment).filter(([key]) => key !== "order").map(([problem, arm]) => `${titleCase(problem)} → ${arm}`).join(", ")}.`);
    notes.push(...night.limitations);
    byId("night-note").textContent = notes.join(" ");
    night.slots.forEach((slot) => list.append(renderSlot(slot)));
  }

  function renderHistory(nights) {
    const list = byId("history-list");
    list.replaceChildren();
    byId("history-count").textContent = `${nights.length} ${nights.length === 1 ? "night" : "nights"}`;
    if (!nights.length) {
      const row = node("tr");
      const cell = node("td", "empty", "No nights recorded.");
      cell.colSpan = 8;
      row.append(cell);
      list.append(row);
      return;
    }
    nights.forEach((night) => {
      const row = node("tr");
      const first = node("td", "", night.date);
      if (night.run_id !== night.date) first.append(node("span", "subtle", ` ${night.run_id}`));
      row.append(first);
      const status = node("td");
      status.append(stamp(titleCase(night.status), statusKind(night.status)));
      row.append(status);
      row.append(node("td", "", `${allowance(night.budget_used)} / ${allowance(night.budget_limit)}`));
      const problems = node("td");
      night.slots.forEach((slot) => {
        const line = node("div", "", `${titleCase(slot.problem)}${slot.arm ? ` · ${slot.arm}` : ""} · ${titleCase(slot.status)}${finite(slot.best?.median_gain) ? ` · best ${pct(slot.best.median_gain)}` : ""}`);
        problems.append(line);
      });
      row.append(problems);
      row.append(node("td", "", night.totals.candidates));
      row.append(node("td", "", night.totals.promising));
      row.append(node("td", night.totals.confirmed ? "gain-up" : "", night.totals.confirmed));
      row.append(node("td", night.totals.publishable ? "gain-up" : "", night.totals.publishable));
      list.append(row);
    });
  }

  function renderIncumbents(incumbents, legacy) {
    const list = byId("incumbent-list");
    list.replaceChildren();
    byId("incumbent-count").textContent = `${incumbents.length} problems`;
    const legacyByProblem = new Map(legacy.map((item) => [item.problem, item]));
    incumbents.forEach((row) => {
      const tr = node("tr");
      tr.append(node("td", "", titleCase(row.problem)));
      tr.append(node("td", "", `${row.record_source} (${row.record_kind})`));
      const incumbent = node("td");
      if (row.incumbent.classification === "confirmed_prior_candidate") {
        incumbent.append(stamp("Confirmed", "good"), node("div", "subtle", `${row.incumbent.evidence_path || ""}`));
      } else {
        incumbent.append(stamp("Historical, unvalidated", "neutral"));
      }
      tr.append(incumbent);
      tr.append(node("td", "", row.targets.length));
      tr.append(node("td", row.beating_record ? "gain-up" : "", row.beating_record));
      tr.append(node("td", row.unsubmitted_beats && row.record_kind === "public" ? "gain-up" : "", row.record_kind === "public" ? row.unsubmitted_beats : `${row.unsubmitted_beats} (baseline, not creditable)`));
      const old = legacyByProblem.get(row.problem);
      tr.append(node("td", "", old ? `${old.iterations} iterations, ${old.champions} champions${old.wins.length ? `, wins: ${old.wins.join(", ")}` : ""}` : "—"));
      list.append(tr);
    });
  }

  async function load() {
    let brief;
    try {
      const response = await fetch("/api/morning");
      brief = await response.json();
      if (!response.ok) throw new Error(brief.message || `Request failed (${response.status}).`);
    } catch (error) {
      byId("night-summary").textContent = `Could not read the brief: ${error.message}`;
      return;
    }
    renderMasthead(brief);
    renderAwaiting(brief.awaiting_publication || []);
    renderNight(brief);
    renderHistory(brief.nights || []);
    renderIncumbents(brief.incumbents || [], brief.legacy || []);
  }

  load();
})();
