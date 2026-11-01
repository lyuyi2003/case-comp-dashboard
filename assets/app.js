/* Everything the page does: load the data, apply the filters, draw the views.

   All text from the data file goes in through textContent (see el below), never
   as HTML. The data contains words collected from the web, and this guarantees
   they can only ever appear as text and can't run as code. */

const CATEGORIES = [
  "consulting/strategy", "sustainability", "finance", "marketing", "policy/economics",
  "insurance/risk", "supply-chain", "social-impact", "other",
];

const STATUS = {
  "open": { label: "Open", icon: "●", tone: "good" },
  "closing-soon": { label: "Closing soon", icon: "▲", tone: "serious" },
  "not-yet-open": { label: "Not yet open", icon: "○", tone: "neutral" },
  "ongoing": { label: "Ongoing", icon: "▶", tone: "neutral" },
  "closed": { label: "Closed", icon: "✕", tone: "muted" },
  "ended": { label: "Ended", icon: "■", tone: "muted" },
  "unconfirmed": { label: "Unconfirmed", icon: "?", tone: "muted" },
};

const ELIGIBILITY = {
  yes: { label: "Eligible", icon: "✓", tone: "good" },
  check: { label: "Check", icon: "?", tone: "warning" },
  no: { label: "Not eligible", icon: "✕", tone: "critical" },
};

const FORMATS = { online: "Online", "in-person": "In-person", hybrid: "Hybrid", unknown: "Not stated" };

const TIMING_TAGS = {
  "registers-before-sem2": "Registers before Sem 2",
  "runs-after-sem2": "Runs after Sem 2",
  "outside-sem2": "Outside Sem 2",
};

const DATE_LABELS = {
  registration_opens: "Registration opens",
  registration_deadline: "Registration deadline",
  case_release: "Case release",
  submission_deadline: "Submission deadline",
  finals: "Finals",
};

const SOURCE_TYPES = { organiser: "Organiser", university: "University", firm: "Firm", news: "News" };
const SOURCE_METHODS = { "page-read": "read directly", "search-index": "seen through a search index" };

const state = {
  search: "", status: "all", category: "all", eligibility: "all", dates: "all", format: "all",
  showOutside: false, showNotEligible: false, sort: "deadline", view: "list", openIds: new Set(),
};

let records = [];
let settings = null;
let updateLog = { runs: [] };
let generatedAt = null;
let today = Rules.todayInSingapore();

const byId = (id) => document.getElementById(id);

// Build an element. Text always goes in as textContent, so it stays plain text.
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  });
  [].concat(children).filter(Boolean).forEach((child) => node.append(child));
  return node;
}

// Only ordinary web links are allowed, so a bad link in the data can't do harm.
function safeUrl(url) {
  return /^https?:\/\//i.test(url || "") ? url : null;
}

function formatDate(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  return new Intl.DateTimeFormat("en-SG", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  }).format(date);
}

function formatMoment(iso) {
  return new Intl.DateTimeFormat("en-SG", {
    weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
    timeZone: "Asia/Singapore",
  }).format(new Date(iso)) + " SGT";
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function countdown(days) {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

function formatKind(text) {
  const value = text.toLowerCase();
  const online = /online|video/.test(value);
  const inPerson = /in-person|in person|on-site|overseas/.test(value);
  if (online && inPerson) return "hybrid";
  if (online) return "online";
  return inPerson ? "in-person" : "unknown";
}

// Add the values that are worked out live, on top of the stored record.
function withLiveValues(record) {
  const dates = Rules.effectiveDates(record, settings);
  return {
    ...record,
    live: {
      status: Rules.computeStatus(record, today, settings),
      dates,
      formatKind: formatKind(record.format),
      isNew: isNew(record),
      searchText: [record.name, record.organiser, record.category, record.description]
        .join(" ").toLowerCase(),
    },
  };
}

function isNew(record) {
  const seen = record.first_seen.slice(0, 10);
  return seen > settings.first_load_date
    && Rules.daysUntil(today, seen) <= settings.new_badge_days;
}

function passesToggles(record) {
  if (record.sem2_relevance === "outside-sem2" && !state.showOutside) return false;
  return record.eligible_for_me !== "no" || state.showNotEligible;
}

function passesFilters(record) {
  const query = state.search.trim().toLowerCase();
  if (query && !record.live.searchText.includes(query)) return false;
  if (state.status !== "all" && record.live.status !== state.status) return false;
  if (state.category !== "all" && record.category !== state.category) return false;
  if (state.eligibility !== "all" && record.eligible_for_me !== state.eligibility) return false;
  if (state.dates !== "all" && record.date_status !== state.dates) return false;
  return state.format === "all" || record.live.formatKind === state.format;
}

// Dates that have passed go after upcoming ones. Records with no date go last.
function dateSortKey(iso) {
  if (!iso) return "9999-99-99";
  return iso < today ? `9000-${iso}` : iso;
}

// A competition that is open with no known deadline could close at any time,
// so it goes first instead of disappearing to the bottom of the list.
function deadlineSortKey(record) {
  const deadline = record.live.dates.registration_deadline;
  if (!deadline && record.live.status === "open") return "0000-00-00";
  return dateSortKey(deadline);
}

function sortRecords(list) {
  const compare = {
    deadline: (a, b) => deadlineSortKey(a).localeCompare(deadlineSortKey(b)),
    finals: (a, b) => dateSortKey(a.live.dates.finals).localeCompare(dateSortKey(b.live.dates.finals)),
    name: (a, b) => a.name.localeCompare(b.name),
    recent: (a, b) => b.first_seen.localeCompare(a.first_seen),
  }[state.sort];
  return [...list].sort((a, b) => compare(a, b) || a.name.localeCompare(b.name));
}

function badge(info) {
  return el("span", { class: `badge tone-${info.tone}` }, [
    el("span", { class: "badge-icon", "aria-hidden": "true", text: info.icon }),
    info.label,
  ]);
}

function dateBadge(record) {
  if (record.date_status === "confirmed") return badge({ label: `Confirmed ${record.edition}`, icon: "✓", tone: "good" });
  if (record.date_status === "expected") return badge({ label: `Expected from ${record.edition}`, icon: "≈", tone: "neutral" });
  return badge({ label: "Dates unknown", icon: "?", tone: "muted" });
}

function deadlineCell(record) {
  const deadline = record.live.dates.registration_deadline;
  if (!deadline) {
    const text = record.organiser_says_open ? "Depends on country" : "Not announced";
    return el("div", { class: "deadline" }, el("span", { class: "deadline-note", text }));
  }

  const days = Rules.daysUntil(deadline, today);
  if (record.date_status !== "expected") {
    return el("div", { class: "deadline" }, [
      el("span", { class: "deadline-date", text: formatDate(deadline) }),
      el("span", { class: "deadline-note", text: countdown(days) }),
    ]);
  }

  const note = days >= 0 ? `estimate: about ${plural(days, "day")} away` : "estimate has passed, check the site";
  return el("div", { class: "deadline" }, [
    el("span", { class: "deadline-date", text: `~${formatDate(deadline)}` }),
    el("span", { class: "deadline-note", text: note }),
  ]);
}

function officialLink(record) {
  const url = safeUrl(record.official_url);
  if (!url) return el("span", { class: "no-link", text: "No official page found" });
  return el("a", {
    class: "official-link", href: url, target: "_blank", rel: "noopener noreferrer",
    text: "Official site", "aria-label": `Official site for ${record.name}`,
    onclick: (event) => event.stopPropagation(),
  });
}

function detailBlock(title, content) {
  return el("div", { class: "detail-block" }, [el("h3", { text: title }), content]);
}

function keyDatesTable(record) {
  const expected = record.date_status === "expected";
  const heads = expected ? ["Stage", `${record.edition} edition`, "2027 estimate"] : ["Stage", "Date"];
  const rows = Rules.DATE_FIELDS.filter((field) => record[field]).map((field) => el("tr", {}, [
    el("th", { scope: "row", text: DATE_LABELS[field] }),
    el("td", { text: formatDate(record[field]) }),
    expected && el("td", { text: `~${formatDate(record.live.dates[field])}` }),
  ]));

  if (rows.length === 0) return el("p", { text: "No dates have been verified yet." });
  return el("table", { class: "dates-table" }, [
    el("thead", {}, el("tr", {}, heads.map((text) => el("th", { scope: "col", text })))),
    el("tbody", {}, rows),
  ]);
}

function sourcesList(record) {
  if (record.source_urls.length === 0) return el("p", { text: "No official source has been found yet." });
  return el("ul", { class: "sources" }, record.source_urls.map((source) => {
    const url = safeUrl(source.url);
    return el("li", {}, [
      url
        ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: source.used_for })
        : source.used_for,
      el("span", {
        class: "source-meta",
        text: `${SOURCE_TYPES[source.source_type]}, ${SOURCE_METHODS[source.method]}, verified ${formatDate(source.last_verified)}`,
      }),
    ]);
  }));
}

function details(record) {
  const panelId = `details-${record.id}`;
  return el("div", { class: "card-details", id: panelId }, [
    el("p", { class: "description", text: record.description }),
    el("div", { class: "detail-grid" }, [
      detailBlock("Key dates", keyDatesTable(record)),
      detailBlock("Team", el("div", {}, [
        el("p", { text: `Size: ${record.team_size}` }),
        record.team_rules !== record.team_size && el("p", { text: `Rules: ${record.team_rules}` }),
      ])),
      detailBlock("Eligibility", el("div", {}, [
        el("p", { text: record.eligibility_text }),
        el("p", { class: "muted-text", text: `For you: ${record.eligibility_reason}.`.replace("..", ".") }),
      ])),
      detailBlock("Prizes", el("p", { text: record.prizes })),
      detailBlock("Format", el("p", { text: record.format })),
      record.sem2_manual_reason && detailBlock("Why this timing tag", el("p", { text: record.sem2_manual_reason })),
    ]),
    record.notes && detailBlock("Notes", el("p", { text: record.notes })),
    detailBlock("Sources", sourcesList(record)),
  ]);
}

function card(record) {
  const open = state.openIds.has(record.id);
  const tag = TIMING_TAGS[record.sem2_relevance];
  const toggle = () => {
    if (open) state.openIds.delete(record.id);
    else state.openIds.add(record.id);
    renderList();
  };

  return el("article", { class: `card${open ? " is-open" : ""}`, id: `card-${record.id}` }, [
    el("div", { class: "card-row", onclick: toggle }, [
      el("div", { class: "card-name" }, [
        el("h2", {}, el("button", {
          type: "button", class: "name-button", "aria-expanded": String(open),
          "aria-controls": `details-${record.id}`, text: record.name,
          onclick: (event) => { event.stopPropagation(); toggle(); },
        })),
        el("p", { class: "organiser", text: record.organiser }),
        el("div", { class: "tags" }, [
          el("span", { class: "tag", text: record.category }),
          tag && el("span", { class: "tag", text: tag }),
          record.live.isNew && el("span", { class: "tag tag-new", text: "New" }),
          record.stale && el("span", { class: "tag tag-stale", text: "Could not refresh" }),
        ]),
      ]),
      el("div", { class: "card-cell" }, badge(STATUS[record.live.status])),
      el("div", { class: "card-cell" }, deadlineCell(record)),
      el("div", { class: "card-cell" }, dateBadge(record)),
      el("div", { class: "card-cell" }, badge(ELIGIBILITY[record.eligible_for_me])),
      el("div", { class: "card-cell card-action" }, officialLink(record)),
    ]),
    open && details(record),
  ]);
}

function clearFilters() {
  state.search = "";
  ["status", "category", "eligibility", "dates", "format"].forEach((key) => { state[key] = "all"; });
  byId("search").value = "";
  ["status", "category", "eligibility", "dates", "format"].forEach((key) => { byId(`filter-${key}`).value = "all"; });
  render();
}

function emptyState() {
  return el("div", { class: "empty" }, [
    el("p", { text: "No competitions match these filters." }),
    el("button", { type: "button", class: "plain-button", text: "Clear filters", onclick: clearFilters }),
  ]);
}

function visibleRecords() {
  return sortRecords(records.filter((record) => passesToggles(record) && passesFilters(record)));
}

function renderList() {
  const list = visibleRecords();
  byId("competition-list").replaceChildren(...(list.length ? list.map(card) : [emptyState()]));
}

function renderCounts() {
  const list = visibleRecords();
  const outside = records.filter((r) => r.sem2_relevance === "outside-sem2").length;
  const notEligible = records.filter((r) => r.eligible_for_me === "no" && r.sem2_relevance !== "outside-sem2").length;
  byId("result-count").textContent = `Showing ${list.length} of ${records.length}`
    + ` (${outside} outside Sem 2, ${notEligible} more not eligible)`;
}

// The summary cards follow the two toggles, but not the other filters.
function renderStats() {
  const scope = records.filter(passesToggles);
  const count = (test) => scope.filter(test).length;
  byId("stat-open").textContent = count((r) => ["open", "closing-soon"].includes(r.live.status));
  byId("stat-closing").textContent = count((r) => r.live.status === "closing-soon");
  byId("stat-not-open").textContent = count((r) => r.live.status === "not-yet-open");
  byId("stat-new").textContent = count((r) => r.live.isNew);

  const unconfirmed = count((r) => r.live.status === "unconfirmed");
  byId("stats-note").textContent = unconfirmed
    ? `${plural(unconfirmed, "competition")} still ${unconfirmed === 1 ? "has" : "have"} no confirmed dates, so ${unconfirmed === 1 ? "it isn't" : "they aren't"} counted above. Dates marked ~ are estimates from the last edition.`
    : "";
}

function renderHeader() {
  const sem = settings.semester_2;
  byId("semester-line").textContent = `NUS ${settings.academic_year} Semester 2, ${formatDate(sem.start)} to ${formatDate(sem.end)}`;
  byId("semester-source").textContent = `Semester dates: ${sem.source_version}.`;
  byId("last-updated").textContent = formatMoment(generatedAt);

  const schedule = settings.schedule;
  const next = schedule.enabled ? Rules.nextScheduledRun(schedule) : null;
  byId("next-update").textContent = next ? formatMoment(next.toISOString()) : "Not scheduled yet";

  const age = Rules.daysUntil(today, Rules.todayInSingapore(new Date(generatedAt)));
  const warning = byId("stale-warning");
  warning.hidden = !(schedule.enabled && age > settings.stale_warning_days);
  warning.textContent = `The data is ${age} days old, so the scheduled update may have stopped. Check that the task is still running.`;
}

function changeItem(text) {
  return el("li", { text });
}

function nameOf(id) {
  const match = records.find((record) => record.id === id);
  return match ? match.name : id;
}

function changeGroup(title, items) {
  if (items.length === 0) return null;
  return el("div", { class: "change-group" }, [el("h3", { text: title }), el("ul", {}, items.map(changeItem))]);
}

function displayValue(value) {
  return value === null || value === undefined ? "none" : String(value);
}

function renderChanges() {
  const run = updateLog.runs[updateLog.runs.length - 1];
  const body = byId("changes-body");
  if (!run) {
    body.replaceChildren(el("p", { class: "muted-text", text: "Nothing yet. Changes will appear here after the first automatic update." }));
    return;
  }

  if (run.error) {
    body.replaceChildren(
      el("p", { text: `The update on ${formatMoment(run.run_time)} failed, so the data was not changed.` }),
      el("p", { class: "muted-text", text: run.error }),
    );
    return;
  }

  const fields = run.fields_changed || [];
  const isDeadline = (change) => Rules.DATE_FIELDS.includes(change.field);
  const describe = (change) => {
    const field = change.field.replaceAll("_", " ");
    const isLong = [change.old_value, change.new_value].some((value) => String(value).length > 40);
    if (isLong) return `${nameOf(change.id)}: ${field} updated`;
    return `${nameOf(change.id)}: ${field} changed from ${displayValue(change.old_value)} to ${displayValue(change.new_value)}`;
  };
  const groups = [
    changeGroup("New competitions", (run.new_competitions || []).map(nameOf)),
    changeGroup("Changed dates", fields.filter(isDeadline).map(describe)),
    changeGroup("Status and other changes", fields.filter((c) => !isDeadline(c)).map(describe)),
    changeGroup("Pages that could not be read", (run.fetch_errors || []).map((e) => `${nameOf(e.id)}: ${e.error}`)),
  ].filter(Boolean);

  const summary = el("p", { class: "muted-text", text: `Update on ${formatMoment(run.run_time)}, ${plural(run.records_checked, "record")} checked.` });
  const quiet = el("p", { text: "No changes in the last update." });
  body.replaceChildren(summary, ...(groups.length ? groups : [quiet]));
}

/* ----- Timeline ----- */

function timelineRange() {
  const start = Rules.dayNumber(settings.timeline.start);
  const end = Rules.dayNumber(settings.timeline.end) + 1;
  const toPercent = (iso) => ((Rules.dayNumber(iso) - start) / (end - start)) * 100;
  return { toPercent };
}

function monthStarts() {
  const months = [];
  let [year, month] = settings.timeline.start.split("-").map(Number);
  const last = settings.timeline.end.slice(0, 7);
  for (;;) {
    const iso = `${year}-${String(month).padStart(2, "0")}-01`;
    if (iso.slice(0, 7) > last) return months;
    months.push(iso);
    month += 1;
    if (month > 12) { month = 1; year += 1; }
  }
}

function monthLabel(iso) {
  return new Intl.DateTimeFormat("en-SG", { month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
}

// The background shared by every row: semester band, month lines, today line.
function trackBackground(range) {
  const sem = settings.semester_2;
  const left = range.toPercent(sem.start);
  const pieces = [el("div", { class: "sem-band", style: `left:${left}%;width:${range.toPercent(sem.end) - left}%` })];
  monthStarts().slice(1).forEach((iso) => {
    pieces.push(el("div", { class: "month-line", style: `left:${range.toPercent(iso)}%` }));
  });
  const now = range.toPercent(today);
  if (now >= 0 && now <= 100) pieces.push(el("div", { class: "today-line", style: `left:${now}%` }));
  return pieces;
}

function showTooltip(target, text) {
  const tip = byId("tooltip");
  tip.textContent = text;
  tip.hidden = false;
  const box = target.getBoundingClientRect();
  const width = tip.offsetWidth;
  const left = Math.min(Math.max(8, box.left + box.width / 2 - width / 2), window.innerWidth - width - 8);
  tip.style.left = `${left + window.scrollX}px`;
  tip.style.top = `${box.top + window.scrollY - tip.offsetHeight - 8}px`;
}

function hideTooltip() {
  byId("tooltip").hidden = true;
}

function timelineMark(range, lane, start, end, label, estimate) {
  const from = range.toPercent(start);
  const to = range.toPercent(end);
  if (to < 0 || from > 100) return null;

  const prefix = estimate ? "Estimate, " : "";
  const when = start === end ? formatDate(start) : `${formatDate(start)} to ${formatDate(end)}`;
  const text = `${label}: ${prefix.toLowerCase()}${when}`;
  const classes = [`mark lane-${lane}`, estimate && "is-estimate"];
  let style;

  if (start === end) {
    classes.push("is-dot");
    style = `left:${from}%`;
  } else {
    const left = Math.max(from, 0);
    const right = Math.min(to, 100);
    if (from < 0) classes.push("runs-in");
    if (to > 100) classes.push("runs-on");
    style = `left:${left}%;width:${right - left}%`;
  }

  return el("button", {
    type: "button", class: classes.filter(Boolean).join(" "), style, "aria-label": text,
    onmouseenter: (event) => showTooltip(event.currentTarget, text),
    onfocus: (event) => showTooltip(event.currentTarget, text),
    onclick: (event) => showTooltip(event.currentTarget, text),
    onmouseleave: hideTooltip,
    onblur: hideTooltip,
  });
}

function registrationWindow(dates) {
  const start = dates.registration_opens || dates.registration_deadline;
  const end = dates.registration_deadline || dates.registration_opens;
  return start ? [start, end] : null;
}

function competitionWindow(dates) {
  const main = Rules.MAIN_PHASE_FIELDS.map((field) => dates[field]).filter(Boolean).sort();
  return main.length ? [main[0], main[main.length - 1]] : null;
}

function openInList(id) {
  state.openIds.add(id);
  setView("list");
  byId(`card-${id}`)?.scrollIntoView({ block: "start" });
}

function timelineRow(range, record) {
  const estimate = record.date_status === "expected";
  const reg = registrationWindow(record.live.dates);
  const comp = competitionWindow(record.live.dates);
  const marks = [
    reg && timelineMark(range, "registration", reg[0], reg[1], "Registration", estimate),
    comp && timelineMark(range, "competition", comp[0], comp[1], "Competition", estimate),
  ].filter(Boolean);
  if (marks.length === 0) return null;

  return el("div", { class: "timeline-row" }, [
    el("button", {
      type: "button", class: "timeline-name", onclick: () => openInList(record.id),
    }, [record.name, estimate && el("span", { class: "estimate-flag", text: " est." })]),
    el("div", { class: "track" }, [...trackBackground(range), ...marks]),
  ]);
}

function timelineLegend() {
  const item = (swatch, text) => el("span", { class: "legend-item" }, [swatch, text]);
  return el("div", { class: "legend" }, [
    item(el("span", { class: "swatch swatch-registration" }), "Registration (top line)"),
    item(el("span", { class: "swatch swatch-competition" }), "Competition (bottom line)"),
    item(el("span", { class: "swatch swatch-registration is-estimate" }), "Faded = estimate"),
    item(el("span", { class: "swatch swatch-semester" }), "Semester 2"),
    item(el("span", { class: "swatch swatch-today" }), "Today"),
  ]);
}

function timelineHeader(range) {
  const months = monthStarts();
  const labels = months.map((iso) => el("span", { class: "month-label", style: `left:${range.toPercent(iso)}%`, text: monthLabel(iso) }));
  return el("div", { class: "timeline-row timeline-head", "aria-hidden": "true" }, [
    el("span", { class: "timeline-name-spacer" }),
    el("div", { class: "track-head" }, labels),
  ]);
}

function renderTimeline() {
  const range = timelineRange();
  const list = visibleRecords();
  const rows = list.map((record) => [record, timelineRow(range, record)]);
  const plotted = rows.filter(([, row]) => row).map(([, row]) => row);
  const missing = rows.filter(([, row]) => !row).map(([record]) => record.name);

  const first = settings.timeline.start;
  const last = settings.timeline.end;
  const caption = `${formatDate(first)} to ${formatDate(last)}. Tap a line for its dates, or a name for the full details.`;
  const parts = [
    el("p", { class: "timeline-caption", text: caption }),
    timelineLegend(),
    plotted.length ? el("div", { class: "timeline" }, [timelineHeader(range), ...plotted]) : emptyState(),
    missing.length > 0 && el("p", {
      class: "timeline-missing", text: `Not shown, because they have no dates in this period: ${missing.join(", ")}.`,
    }),
  ];
  byId("timeline").replaceChildren(...parts.filter(Boolean));
}

/* ----- Wiring it together ----- */

function setView(view) {
  state.view = view;
  const list = view === "list";
  byId("tab-list").setAttribute("aria-selected", String(list));
  byId("tab-timeline").setAttribute("aria-selected", String(!list));
  byId("view-list").hidden = !list;
  byId("view-timeline").hidden = list;
  render();
}

// Filters can be folded away on a phone, so the heading says when any are on.
function renderFilterSummary() {
  const filters = ["status", "category", "eligibility", "dates", "format"];
  const active = filters.filter((key) => state[key] !== "all").length
    + (state.showOutside ? 1 : 0) + (state.showNotEligible ? 1 : 0);
  byId("filter-summary").textContent = `Filters and sort${active ? ` (${active} on)` : ""}`;
}

function render() {
  renderStats();
  renderCounts();
  renderFilterSummary();
  if (state.view === "list") renderList();
  else renderTimeline();
}

function fillSelect(id, allLabel, options) {
  const select = byId(id);
  select.replaceChildren(
    el("option", { value: "all", text: allLabel }),
    ...options.map(([value, label]) => el("option", { value, text: label })),
  );
}

function setUpControls() {
  // Start with the filters folded on a phone, so the list comes first.
  byId("filter-panel").open = !window.matchMedia("(max-width: 720px)").matches;

  fillSelect("filter-status", "Any status", Object.entries(STATUS).map(([key, info]) => [key, info.label]));
  fillSelect("filter-category", "Any category", CATEGORIES.map((name) => [name, name]));
  fillSelect("filter-eligibility", "Any eligibility", Object.entries(ELIGIBILITY).map(([key, info]) => [key, info.label]));
  fillSelect("filter-dates", "Any dates", [["confirmed", "Confirmed"], ["expected", "Expected"], ["unknown", "Unknown"]]);
  fillSelect("filter-format", "Any format", Object.entries(FORMATS));

  ["status", "category", "eligibility", "dates", "format"].forEach((key) => {
    byId(`filter-${key}`).addEventListener("change", (event) => { state[key] = event.target.value; render(); });
  });
  byId("search").addEventListener("input", (event) => { state.search = event.target.value; render(); });
  byId("sort").addEventListener("change", (event) => { state.sort = event.target.value; render(); });

  byId("show-outside").addEventListener("change", (event) => {
    state.showOutside = event.target.checked;
    render();
  });
  byId("show-not-eligible").addEventListener("change", (event) => {
    state.showNotEligible = event.target.checked;
    render();
  });

  byId("tab-list").addEventListener("click", () => setView("list"));
  byId("tab-timeline").addEventListener("click", () => setView("timeline"));
}

async function loadJson(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

// Keep countdowns right if the page stays open past midnight.
function watchForNewDay() {
  setInterval(() => {
    const now = Rules.todayInSingapore();
    if (now === today) return;
    today = now;
    records = records.map(withLiveValues);
    renderHeader();
    render();
  }, 60000);
}

async function start() {
  setUpControls();
  try {
    const [data, config] = await Promise.all([
      loadJson("data/competitions.json"),
      loadJson("config/settings.json"),
    ]);
    settings = config;
    generatedAt = data.generated_at;
    records = data.competitions.map(withLiveValues);
    updateLog = await loadJson("data/update-log.json").catch(() => updateLog);

    renderHeader();
    renderChanges();
    render();
    watchForNewDay();
  } catch (error) {
    const box = byId("load-error");
    box.hidden = false;
    box.textContent = "The competition data could not be loaded. If you opened this file directly, run \"python -m http.server 8000\" in the project folder, then open http://localhost:8000 instead.";
    console.error(error);
  }
}

start();
