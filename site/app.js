"use strict";

const pageRoot = document.getElementById("page-root");
const navButtons = Array.from(document.querySelectorAll(".nav-link"));
const sectionName = document.getElementById("section-name");
const sidebar = document.getElementById("sidebar");
const menuButton = document.getElementById("menu-button");

const pageNames = {
  overview: "OVERVIEW",
  batting: "BATTING",
  bowling: "BOWLING",
  insights: "COACH INSIGHTS",
  players: "PLAYER EXPLORER",
  pressure: "PRESSURE MODEL",
  technical: "TECHNICAL RANKINGS",
  robustness: "ROBUSTNESS",
  quality: "DATA QUALITY"
};

let dashboardData;
let currentPage = "overview";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function isNumeric(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function number(value, digits = 1) {
  if (!isNumeric(value)) return "—";
  const parsed = Number(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(parsed);
}

function integer(value) {
  return number(value, 0);
}

function percentage(value, digits = 1) {
  if (!isNumeric(value)) return "—";
  const parsed = Number(value);
  return `${number(parsed * 100, digits)}%`;
}

function dateLabel(value) {
  if (!value) return "date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function heading(title, description, eyebrow = "SAVED EXPLORATORY RESULTS") {
  return `
    <div class="page-heading">
      <div>
        <div class="eyebrow">${escapeHtml(eyebrow)}</div>
        <h1>${escapeHtml(title)}</h1>
        <p class="page-description">${escapeHtml(description)}</p>
      </div>
      <span class="exploratory-pill">EXPLORATORY ONLY</span>
    </div>`;
}

function kpi(label, value, note = "", blue = false) {
  return `
    <article class="kpi-card${blue ? " blue" : ""}">
      <div class="kpi-label">${escapeHtml(label)}</div>
      <div class="kpi-value">${escapeHtml(value)}</div>
      ${note ? `<div class="kpi-note">${escapeHtml(note)}</div>` : ""}
    </article>`;
}

function sectionTitle(title, note = "") {
  return `<div class="section-title"><h2>${escapeHtml(title)}</h2>${note ? `<span>${escapeHtml(note)}</span>` : ""}</div>`;
}

function valueForCell(key, value) {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "rank") return integer(value);
  if (typeof value === "number") {
    if (key.includes("rate") || key.includes("economy") || key.includes("strike_rate")) {
      return number(value, 2);
    }
    if (key === "consistency" && value <= 1) return percentage(value);
    return number(value, 2);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function rankCell(value, blue) {
  return `<span class="rank-badge${blue ? " blue" : ""}">${escapeHtml(integer(value))}</span>`;
}

function table(rows, columns, options = {}) {
  if (!rows || rows.length === 0) {
    return `<div class="empty-state">No saved rows are available for this selection.</div>`;
  }
  const blue = Boolean(options.blue);
  const body = rows.map((row) => `
    <tr>${columns.map((column) => {
      const value = row[column.key];
      const cell = column.key === "rank"
        ? rankCell(value, blue)
        : escapeHtml(valueForCell(column.key, value));
      return `<td>${cell}</td>`;
    }).join("")}</tr>`).join("");
  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function autoColumns(rows, limit = 9) {
  const keys = Object.keys(rows[0] || {}).slice(0, limit);
  return keys.map((key) => ({
    key,
    label: key.replaceAll("_", " ")
  }));
}

function barChart(rows, labelKey, valueKey, color = "pink", digits = 1) {
  const valid = rows
    .filter((row) => isNumeric(row[valueKey]))
    .slice(0, 10);
  if (valid.length === 0) return `<div class="empty-state">No chart data is available.</div>`;
  const max = Math.max(...valid.map((row) => Number(row[valueKey])), 0.0001);
  return `<div class="bar-chart">${valid.map((row) => {
    const value = Number(row[valueKey]);
    const width = Math.max(2, (value / max) * 100);
    return `
      <div class="bar-row">
        <span class="bar-label" title="${escapeHtml(row[labelKey])}">${escapeHtml(row[labelKey])}</span>
        <div class="bar-track"><div class="bar-fill${color === "blue" ? " blue" : ""}" style="width:${width.toFixed(2)}%"></div></div>
        <span class="bar-value">${escapeHtml(number(value, digits))}</span>
      </div>`;
  }).join("")}</div>`;
}

function lineChart(rows, valueKey) {
  const valid = rows.filter((row) => isNumeric(row[valueKey]));
  if (valid.length < 2) return `<div class="empty-state">Not enough match-level values to draw a trend.</div>`;
  const width = 720;
  const height = 190;
  const padX = 28;
  const padY = 18;
  const values = valid.map((row) => Number(row[valueKey]));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((value, index) => {
    const x = padX + (index / (values.length - 1)) * (width - 2 * padX);
    const y = height - padY - ((value - min) / span) * (height - 2 * padY);
    return { x, y, value };
  });
  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");
  const dots = points.map((point, index) => `
    <circle class="chart-dot" cx="${point.x}" cy="${point.y}" r="3.2">
      <title>Match ${escapeHtml(valid[index].match_id)}: ${escapeHtml(number(point.value, 2))}</title>
    </circle>`).join("");
  const lines = [0, 0.5, 1].map((fraction) => {
    const y = padY + fraction * (height - 2 * padY);
    return `<line class="grid-line" x1="${padX}" y1="${y}" x2="${width - padX}" y2="${y}"></line>`;
  }).join("");
  return `
    <svg class="line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Match trend">
      ${lines}<polyline class="chart-line" points="${polyline}"></polyline>${dots}
    </svg>`;
}

function csvEscape(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv(filename, rows) {
  if (!rows || rows.length === 0) return;
  const columns = Object.keys(rows[0]);
  const content = [
    columns.map(csvEscape).join(","),
    ...rows.map((row) => columns.map((key) => csvEscape(row[key])).join(","))
  ].join("\r\n");
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function tableCard(title, rows, columns, note = "", options = {}) {
  return `
    <section class="card">
      <div class="chart-heading">
        <div><h3>${escapeHtml(title)}</h3>${note ? `<p>${escapeHtml(note)}</p>` : ""}</div>
        ${options.download ? `<button class="button secondary" data-download="${escapeHtml(options.download)}">Download CSV</button>` : ""}
      </div>
      ${table(rows, columns, options)}
    </section>`;
}

function contexts(row) {
  const context = String(row.comparison_context ?? row.comparison_group ?? "").trim();
  return context ? context.split(",").map((part) => part.trim()).filter(Boolean) : [];
}

function competitionOptions(rows) {
  return [...new Set(rows.flatMap(contexts))].sort((a, b) => a.localeCompare(b));
}

function filterRows(rows, search, competition) {
  const term = search.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    const matchesCompetition = competition === "all" || contexts(row).includes(competition);
    const text = `${row.player_name ?? ""} ${row.striker_id ?? ""} ${row.bowler_id ?? ""}`.toLocaleLowerCase();
    return matchesCompetition && (!term || text.includes(term));
  });
}

function rankingColumns(role, technical) {
  if (technical) return autoColumns(dashboardData.rankings[role].full[0] ? [dashboardData.rankings[role].full[0]] : [], 40);
  const common = [
    { key: "rank", label: "Rank" },
    { key: "player_name", label: "Player" },
    { key: role === "batter" ? "striker_id" : "bowler_id", label: "Player ID" },
    { key: "comparison_context", label: "Competition" }
  ];
  const metrics = role === "batter"
    ? [
      { key: "pressure_runs", label: "Pressure runs" },
      { key: "pressure_balls", label: "Pressure balls" },
      { key: "pressure_strike_rate", label: "Pressure SR" },
      { key: "pressure_strike_rate_shrunk", label: "Adjusted SR" },
      { key: "consistency", label: "Consistency" },
      { key: "composite_score", label: "Score" }
    ]
    : [
      { key: "pressure_wickets", label: "Pressure wickets" },
      { key: "legal_pressure_balls", label: "Legal balls" },
      { key: "pressure_economy", label: "Pressure economy" },
      { key: "pressure_economy_shrunk", label: "Adjusted economy" },
      { key: "consistency", label: "Consistency" },
      { key: "composite_score", label: "Score" }
    ];
  return common.concat(metrics);
}

function renderRankingPage(role, technical = false) {
  const info = dashboardData.rankings[role];
  const roleTitle = role === "batter" ? "Batting Under Pressure" : "Bowling Under Pressure";
  const title = technical ? `Technical ${roleTitle}` : roleTitle;
  const fullRows = info.full;
  const groups = competitionOptions(fullRows);
  const columns = rankingColumns(role, technical);
  const metricKey = role === "batter" ? "pressure_strike_rate" : "pressure_economy";
  const chartTitle = role === "batter" ? "Top pressure strike rates" : "Lowest pressure economy";
  const chartRows = [...info.top10]
    .sort((a, b) => role === "batter"
      ? Number(b[metricKey] || 0) - Number(a[metricKey] || 0)
      : Number(a[metricKey] || Infinity) - Number(b[metricKey] || Infinity));
  pageRoot.innerHTML = `
    ${heading(title, technical
      ? "Full saved metrics and ranking fields. No ranking is recalculated in this site."
      : "Search and filter the saved leaderboard by comparison group. These are assumption-based, exploratory rankings.")}
    ${technical ? "" : `
      <div class="grid grid-2" style="margin-top:16px">
        <section class="card chart-card">
          <div class="chart-heading"><div><h3>${escapeHtml(chartTitle)}</h3><p>Saved Top 10 results, filtered to the selected group.</p></div></div>
          <div id="ranking-chart"></div>
        </section>
        <section class="card">
          <h3>Ranking notes</h3>
          <div class="metric-list">
            <div class="metric-item"><span>Players in full ranking</span><strong>${integer(fullRows.length)}</strong></div>
            <div class="metric-item"><span>Saved Top 10 rows</span><strong>${integer(info.top10.length)}</strong></div>
            <div class="metric-item"><span>Comparison groups</span><strong>${integer(groups.length)}</strong></div>
          </div>
          <p class="note">Ranks are preserved from the analysis output. Filters do not recompute scores.</p>
        </section>
      </div>`}
    <div class="filters">
      <input id="ranking-search" class="field" type="search" placeholder="Search player or ID" aria-label="Search rankings">
      <select id="group-filter" class="select-field" aria-label="Competition comparison group">
        <option value="all">All comparison groups</option>
        ${groups.map((group) => `<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`).join("")}
      </select>
      ${technical ? `
        <select id="technical-role" class="select-field" aria-label="Technical ranking type">
          <option value="batter"${role === "batter" ? " selected" : ""}>Batter metrics</option>
          <option value="bowler"${role === "bowler" ? " selected" : ""}>Bowler metrics</option>
        </select>` : ""}
      <button id="ranking-download" class="button secondary">Download ${technical ? "full rankings" : "Top 10"}</button>
      <span class="muted" id="ranking-count"></span>
    </div>
    <div id="ranking-table"></div>`;

  const search = document.getElementById("ranking-search");
  const group = document.getElementById("group-filter");
  const body = document.getElementById("ranking-table");
  const count = document.getElementById("ranking-count");
  const render = () => {
    const filtered = filterRows(fullRows, search.value, group.value);
    count.textContent = `${integer(filtered.length)} players`;
    body.innerHTML = table(filtered, columns, { blue: role === "bowler" });
    const chart = document.getElementById("ranking-chart");
    if (chart) {
      const filteredTop = filterRows(chartRows, "", group.value);
      chart.innerHTML = barChart(
        filteredTop,
        "player_name",
        metricKey,
        role === "bowler" ? "blue" : "pink",
        2
      );
    }
  };
  search.addEventListener("input", render);
  group.addEventListener("change", render);
  const technicalRole = document.getElementById("technical-role");
  if (technicalRole) {
    technicalRole.addEventListener("change", () => renderRankingPage(technicalRole.value, true));
  }
  document.getElementById("ranking-download").addEventListener("click", () => {
    downloadCsv(`${role}_${technical ? "full_rankings" : "top_10"}.csv`, technical ? fullRows : info.top10);
  });
  render();
}

function renderOverview() {
  const batterRows = dashboardData.rankings.batter.full;
  const bowlerRows = dashboardData.rankings.bowler.full;
  const rankedBatters = batterRows.filter((row) => isNumeric(row.rank) && Number(row.rank) >= 1);
  const rankedBowlers = bowlerRows.filter((row) => isNumeric(row.rank) && Number(row.rank) >= 1);
  const batterTop = [...rankedBatters].sort((a, b) => Number(a.rank) - Number(b.rank))[0];
  const bowlerTop = [...rankedBowlers].sort((a, b) => Number(a.rank) - Number(b.rank))[0];
  const fastest = [...rankedBatters].filter((row) => isNumeric(row.pressure_strike_rate))
    .sort((a, b) => Number(b.pressure_strike_rate) - Number(a.pressure_strike_rate))[0];
  const tightest = [...rankedBowlers].filter((row) => isNumeric(row.pressure_economy))
    .sort((a, b) => Number(a.pressure_economy) - Number(b.pressure_economy))[0];
  const gradient = dashboardData.pressure_validation.outcome_gradient;

  pageRoot.innerHTML = `
    <section class="hero">
      <span class="exploratory-pill">EXPLORATORY ANALYSIS</span>
      <div class="eyebrow">SUPERR SELECTOR · CRICKET ANALYTICS</div>
      <h1>Batman Plays Under Pressure</h1>
      <p>Explore saved batting and bowling performance in high-pressure T20 chases.</p>
      <div class="hero-meta">Saved run ${escapeHtml(dashboardData.manifest.run_id)} · Completed ${escapeHtml(dateLabel(dashboardData.manifest.completed_at))}</div>
    </section>
    ${sectionTitle("Featured performers", "Leaders follow the saved composite ranking")}
    <div class="grid grid-2">
      ${renderFeatured(batterTop, "batter")}
      ${renderFeatured(bowlerTop, "bowler")}
    </div>
    ${sectionTitle("A quick read", "Descriptive leaders from saved full rankings")}
    <div class="grid grid-2">
      <section class="card">
        <div class="eyebrow">FASTEST PRESSURE SCORING</div>
        ${fastest ? `<h2>${escapeHtml(fastest.player_name)}</h2><p class="inline-stat">${escapeHtml(number(fastest.pressure_strike_rate, 2))}<span class="muted"> runs / 100 balls</span></p><p class="muted">Across ${integer(fastest.pressure_balls)} pressure balls · ${escapeHtml(fastest.comparison_context || "comparison group unavailable")}</p>` : `<p class="muted">No saved batter rate is available.</p>`}
      </section>
      <section class="card">
        <div class="eyebrow">TIGHTEST PRESSURE ECONOMY</div>
        ${tightest ? `<h2>${escapeHtml(tightest.player_name)}</h2><p class="inline-stat" style="color:var(--blue)">${escapeHtml(number(tightest.pressure_economy, 2))}<span class="muted"> runs / over</span></p><p class="muted">Across ${integer(tightest.legal_pressure_balls)} legal pressure balls · ${escapeHtml(tightest.comparison_context || "comparison group unavailable")}</p>` : `<p class="muted">No saved bowler rate is available.</p>`}
      </section>
    </div>
    ${sectionTitle("Pressure outcome gradient", "Observed chasing-team win rate by saved pressure band")}
    <section class="card chart-card">
      <div class="chart-heading"><div><h3>Win rate by pressure band</h3><p>These are observational summaries and depend on exploratory assumptions.</p></div></div>
      ${barChart(gradient, "pressure_band", "win_rate", "blue", 2)}
      <p class="note">Bars show win-rate proportions; see Pressure Model for confidence intervals and diagnostics.</p>
    </section>
  `;
}

function renderFeatured(row, role) {
  if (!row) {
    return `<section class="card"><p class="muted">No saved ${role} leader is available.</p></section>`;
  }
  const batter = role === "batter";
  const value = batter ? row.pressure_runs : row.pressure_wickets;
  const descriptor = batter ? "pressure runs" : "pressure wickets";
  return `
    <section class="card player-card">
      <div class="player-card-top">
        <span class="player-avatar${batter ? "" : " blue"}">${batter ? "BAT" : "BOWL"}</span>
        <span><small class="${batter ? "" : "blue-text"}">TOP PRESSURE ${batter ? "BATTER" : "BOWLER"}</small><strong>${escapeHtml(row.player_name)}</strong></span>
      </div>
      <div class="player-card-body">
        <div class="player-card-stat">${escapeHtml(integer(value))}<small>${descriptor} · rank ${escapeHtml(integer(row.rank))}</small></div>
        <button class="card-link" data-go="${batter ? "batting" : "bowling"}">View rankings →</button>
      </div>
    </section>`;
}

function renderInsights() {
  const batterRows = dashboardData.rankings.batter.top10;
  const bowlerRows = dashboardData.rankings.bowler.top10;
  const leaders = [
    { label: "Most pressure runs", rows: batterRows, metric: "pressure_runs", role: "Batter", max: true },
    { label: "Highest pressure strike rate", rows: batterRows, metric: "pressure_strike_rate", role: "Batter", max: true },
    { label: "Most pressure wickets", rows: bowlerRows, metric: "pressure_wickets", role: "Bowler", max: true },
    { label: "Lowest pressure economy", rows: bowlerRows, metric: "pressure_economy", role: "Bowler", max: false },
    { label: "Best batting consistency", rows: batterRows, metric: "consistency", role: "Batter", max: true },
    { label: "Best bowling consistency", rows: bowlerRows, metric: "consistency", role: "Bowler", max: true }
  ];
  const cards = leaders.map((item) => {
    const candidates = item.rows.filter((row) => isNumeric(row[item.metric]));
    candidates.sort((a, b) => item.max
      ? Number(b[item.metric]) - Number(a[item.metric])
      : Number(a[item.metric]) - Number(b[item.metric]));
    const row = candidates[0];
    return `
      <section class="card">
        <div class="eyebrow">${escapeHtml(item.role.toUpperCase())} LEADER</div>
        <h3>${escapeHtml(item.label)}</h3>
        ${row
          ? `<p class="inline-stat">${escapeHtml(valueForCell(item.metric, row[item.metric]))}</p><p><strong>${escapeHtml(row.player_name)}</strong></p><p class="muted">Saved rank ${integer(row.rank)} · ${escapeHtml(row.comparison_context || "comparison group unavailable")}</p>`
          : `<p class="muted">No saved Top 10 data is available for this metric.</p>`}
      </section>`;
  }).join("");
  pageRoot.innerHTML = `
    ${heading("Coach Insights", "Quick, descriptive leaders drawn only from the saved Top 10 batter and bowler lists.")}
    <div class="grid grid-3">${cards}</div>
    <div class="callout blue" style="margin-top:18px"><strong>Coach's note:</strong> These comparisons are descriptive. Differences in competition, sample size, role, and source assumptions should be considered before making selection decisions.</div>`;
}

function renderPlayers() {
  const uniquePlayers = (rows, role, idColumn) => {
    const playersById = new Map();
    for (const row of rows) {
      const id = String(row[idColumn] ?? "");
      if (!id) continue;
      const previous = playersById.get(id);
      const currentRank = isNumeric(row.rank) && Number(row.rank) >= 1
        ? Number(row.rank)
        : Number.POSITIVE_INFINITY;
      const previousRank = previous && isNumeric(previous.row.rank) && Number(previous.row.rank) >= 1
        ? Number(previous.row.rank)
        : Number.POSITIVE_INFINITY;
      if (!previous || currentRank < previousRank) {
        playersById.set(id, {
          id,
          name: String(row.player_name ?? id),
          role,
          row
        });
      }
    }
    return [...playersById.values()];
  };
  const players = [
    ...uniquePlayers(dashboardData.rankings.batter.full, "batter", "striker_id"),
    ...uniquePlayers(dashboardData.rankings.bowler.full, "bowler", "bowler_id")
  ].sort((a, b) => a.name.localeCompare(b.name));
  pageRoot.innerHTML = `
    ${heading("Player Explorer", "Explore saved player metrics and aggregated match/phase profiles. No delivery-level source rows are published.")}
    <section class="card">
      <div class="filters">
        <select id="player-role" class="select-field" aria-label="Player role">
          <option value="all">All roles</option><option value="batter">Batters</option><option value="bowler">Bowlers</option>
        </select>
        <input id="player-search" class="field" type="search" placeholder="Search player name or ID" aria-label="Search players">
        <select id="player-select" class="select-field player-select" aria-label="Select player"></select>
      </div>
      <div id="player-detail"></div>
    </section>`;

  const roleSelect = document.getElementById("player-role");
  const search = document.getElementById("player-search");
  const playerSelect = document.getElementById("player-select");
  const detail = document.getElementById("player-detail");
  let selectedKey = "";

  const refreshOptions = () => {
    const filtered = players.filter((player) => {
      const roleMatches = roleSelect.value === "all" || roleSelect.value === player.role;
      const haystack = `${player.name} ${player.id}`.toLocaleLowerCase();
      return roleMatches && haystack.includes(search.value.trim().toLocaleLowerCase());
    });
    playerSelect.innerHTML = filtered.map((player) => {
      const key = `${player.role}:${player.id}`;
      return `<option value="${escapeHtml(key)}">${escapeHtml(player.name)} · ${player.role} · ${escapeHtml(player.row.comparison_context || "all contexts")}</option>`;
    }).join("");
    if (filtered.some((player) => `${player.role}:${player.id}` === selectedKey)) {
      playerSelect.value = selectedKey;
    } else {
      selectedKey = playerSelect.value;
    }
    renderDetail();
  };

  const renderDetail = () => {
    const player = players.find((candidate) => `${candidate.role}:${candidate.id}` === playerSelect.value);
    if (!player) {
      detail.innerHTML = `<div class="empty-state">No player matches this search.</div>`;
      return;
    }
    selectedKey = playerSelect.value;
    const row = player.row;
    const profile = dashboardData.profiles[player.role][player.id] || { matches: [], phases: [] };
    const batter = player.role === "batter";
    const metrics = batter
      ? [
        ["Saved rank", integer(row.rank)],
        ["Pressure runs", integer(row.pressure_runs)],
        ["Pressure balls", integer(row.pressure_balls)],
        ["Pressure SR", number(row.pressure_strike_rate, 2)],
        ["Normal SR", number(row.normal_strike_rate, 2)]
      ]
      : [
        ["Saved rank", integer(row.rank)],
        ["Pressure wickets", integer(row.pressure_wickets)],
        ["Pressure economy", number(row.pressure_economy, 2)],
        ["Normal economy", number(row.normal_economy, 2)],
        ["Legal pressure balls", integer(row.legal_pressure_balls)]
      ];
    const rateKey = batter ? "pressure_strike_rate" : "pressure_economy";
    const rateLabel = batter ? "Pressure strike rate by match" : "Pressure economy by match";
    const profileColumns = [
      { key: "match_id", label: "Match ID" },
      { key: "pressure_runs", label: "Pressure runs conceded/scored" },
      { key: "pressure_balls", label: batter ? "Pressure balls faced" : "Legal pressure balls" },
      { key: rateKey, label: rateKey.replaceAll("_", " ") }
    ];
    const phases = [...profile.phases].sort((a, b) => String(a.phase).localeCompare(String(b.phase)));
    detail.innerHTML = `
      <hr class="section-divider">
      <div class="page-heading">
        <div><div class="eyebrow">${batter ? "BATTER" : "BOWLER"} PROFILE</div><h2>${escapeHtml(player.name)}</h2><p class="muted">Player ID ${escapeHtml(player.id)} · Comparison group ${escapeHtml(player.row.comparison_context || "context unavailable")}</p></div>
        <span class="exploratory-pill">EXPLORATORY METRICS</span>
      </div>
      <div class="grid grid-4">${metrics.map(([label, value], index) => kpi(label, value, "", !batter && index % 2 === 1)).join("")}</div>
      <div class="grid grid-2" style="margin-top:16px">
        <section class="card">
          <h3>${escapeHtml(rateLabel)}</h3>
          <p class="muted">Aggregated from saved high-pressure states; no ball-by-ball records are included in the site data.</p>
          <div class="profile-chart">${lineChart(profile.matches, rateKey)}</div>
        </section>
        <section class="card">
          <h3>High-pressure phase profile</h3>
          ${table(phases, [
            { key: "phase", label: "Phase" },
            { key: "pressure_runs", label: "Runs" },
            { key: "pressure_balls", label: "Balls" },
            { key: "rate", label: batter ? "Strike rate" : "Economy" }
          ], { blue: !batter })}
        </section>
      </div>
      <div style="margin-top:16px">${tableCard("Match-level profile", profile.matches, profileColumns, `${integer(profile.matches.length)} matches with saved profile rows`)}</div>`;
  };

  roleSelect.addEventListener("change", refreshOptions);
  search.addEventListener("input", refreshOptions);
  playerSelect.addEventListener("change", renderDetail);
  refreshOptions();
}

function renderPressure() {
  const config = dashboardData.config.pressure;
  const weights = config.weights || {};
  const coverage = dashboardData.coverage;
  const gradient = dashboardData.pressure_validation.outcome_gradient || [];
  const ablations = dashboardData.pressure_validation.ablations || [];
  const components = dashboardData.pressure_distributions.components || [];
  const correlations = Object.entries(dashboardData.pressure_validation.correlations || {})
    .map(([pair, value]) => ({ pair: pair.replace("_", " / "), correlation: value }));
  pageRoot.innerHTML = `
    ${heading("Pressure Model", "Saved diagnostics for the pre-delivery pressure score. This page does not run validation or recalculate rankings.")}
    <div class="callout"><strong>Exploratory:</strong> the score is evaluated under configured assumptions that are not confirmed by an authoritative source.</div>
    ${sectionTitle("Model definition")}
    <section class="card">
      <div class="formula">P = ${number(weights.required_rate, 2)}R + ${number(weights.wickets_lost, 2)}W + ${number(weights.chase_difficulty, 2)}D + ${number(weights.innings_stage, 2)}S</div>
      <p class="muted">Components are clamped to [0, 1]. High pressure begins at P ≥ ${number(config.high_pressure_threshold, 2)}; clutch pressure begins at P ≥ ${number(config.clutch_threshold, 2)}.</p>
      <div class="grid grid-4">
        ${kpi("Matches in pressure validation", integer(coverage.distinct_matches))}
        ${kpi("Valid delivery rows", integer(coverage.valid_delivery_rows), "", true)}
        ${kpi("High-pressure share", percentage(coverage.high_pressure_delivery_share))}
        ${kpi("Pressure rows with unresolved winner", integer(coverage.unresolved_winner_rows), "", true)}
      </div>
    </section>
    ${sectionTitle("Observed win-rate gradient", "Saved match-level confidence bounds are listed in the table")}
    <div class="grid grid-2">
      <section class="card"><h3>Win rate by pressure band</h3><div style="margin-top:15px">${barChart(gradient, "pressure_band", "win_rate", "pink", 2)}</div></section>
      <section class="card"><h3>Outcome-gradient evidence</h3>${table(gradient, [
        { key: "pressure_band", label: "Pressure band" },
        { key: "delivery_rows", label: "Rows" },
        { key: "distinct_matches", label: "Matches" },
        { key: "win_rate", label: "Win rate" },
        { key: "ci95_low", label: "95% low" },
        { key: "ci95_high", label: "95% high" }
      ])}</section>
    </div>
    ${sectionTitle("Observed score distribution")}
    <section class="card">
      <h3>Live-chase pressure scores</h3>
      <p class="muted">Saved score counts by 0.1-wide pressure interval.</p>
      ${barChart(dashboardData.pressure_distributions.histogram || [], "label", "count", "pink", 0)}
    </section>
    ${sectionTitle("Component distribution")}
    ${tableCard("Saved component summaries", components, [
      { key: "component", label: "Component" },
      { key: "count", label: "States" },
      { key: "mean", label: "Mean" },
      { key: "median", label: "Median" },
      { key: "q25", label: "25th percentile" },
      { key: "q75", label: "75th percentile" }
    ])}
    <div class="grid grid-2" style="margin-top:16px">
      ${tableCard("Saved model ablations", ablations, [
        { key: "name", label: "Model" },
        { key: "status", label: "Status" },
        { key: "test_matches", label: "Test matches" },
        { key: "auc", label: "AUC" },
        { key: "brier", label: "Brier score" }
      ])}
      ${tableCard("Component correlations", correlations, [
        { key: "pair", label: "Component pair" },
        { key: "correlation", label: "Correlation" }
      ])}
    </div>
    ${(dashboardData.pressure_validation.diagnostics || []).length
      ? `<div class="callout blue" style="margin-top:16px"><strong>Diagnostics:</strong> ${dashboardData.pressure_validation.diagnostics.map(escapeHtml).join("<br>")}</div>`
      : ""}`;
}

function renderRobustness() {
  const labels = {
    batter_sensitivity: "Batter metric sensitivity",
    bowler_sensitivity: "Bowler metric sensitivity",
    scenario_stability: "Scenario stability",
    bootstrap_results: "Saved bootstrap results",
    batter_bootstrap_summary: "Batter bootstrap summary",
    bowler_bootstrap_summary: "Bowler bootstrap summary",
    stability_adjusted_top10: "Stability-adjusted Top 10"
  };
  const tables = Object.entries(dashboardData.robustness || {}).filter(([, rows]) => rows.length > 0);
  const sections = tables.map(([name, rows]) => `
    <section class="card" style="margin-top:14px">
      <div class="chart-heading"><div><h3>${escapeHtml(labels[name] || name)}</h3><p>Existing saved output; this page does not run robustness analysis.</p></div><button class="button secondary" data-download="${escapeHtml(name)}">Download CSV</button></div>
      ${table(rows.slice(0, 250), autoColumns(rows, 12))}
    </section>`).join("");
  pageRoot.innerHTML = `
    ${heading("Robustness", "Previously saved exploratory sensitivity and stability outputs. No bootstrap, sensitivity, or scenario analysis is run by this site.")}
    <div class="callout blue"><strong>Scope:</strong> these diagnostics describe the assumption-based rankings; they do not establish source-validated results.</div>
    ${tables.length ? sections : `<div class="empty-state" style="margin-top:16px">No optional robustness output was saved for this run.</div>`}`;
}

function renderQuality() {
  const quality = dashboardData.quality;
  const evidence = quality.source_evidence || [];
  const findings = quality.findings || [];
  const tables = Object.entries(quality.tables || {}).map(([name, details]) => ({ table: name, ...details }));
  const schemaGroups = Object.entries(quality.schemas || {}).map(([name, columns]) => `
    <details class="schema-group">
      <summary>${escapeHtml(name)} · ${integer(columns.length)} columns</summary>
      ${table(columns, [
        { key: "column", label: "Column" },
        { key: "dtype", label: "Type" },
        { key: "null_count", label: "Nulls" },
        { key: "distinct_non_null", label: "Distinct values" }
      ])}
    </details>`).join("");
  const exclusions = quality.confirmed_exclusions || {};
  const superOvers = exclusions.super_overs || {};
  const revised = exclusions.revised_conditions || {};
  pageRoot.innerHTML = `
    ${heading("Data Quality & Methodology", "Source evidence, limitations, and exclusions retained with the saved run.")}
    <div class="callout"><strong>EXPLORATORY ONLY:</strong> audit findings are diagnostics and do not gate the saved rankings. Scoring assumptions remain unconfirmed.</div>
    ${sectionTitle("Saved source inventory")}
    ${tableCard("Audited input tables", tables, [
      { key: "table", label: "Table" },
      { key: "rows", label: "Rows" },
      { key: "columns", label: "Columns" },
      { key: "duplicate_full_rows", label: "Duplicate full rows" }
    ])}
    <div class="grid grid-2" style="margin-top:16px">
      <section class="card">
        <h3>Source evidence</h3>
        ${table(evidence, [
          { key: "gate_id", label: "Evidence topic" },
          { key: "status", label: "Status" },
          { key: "affected_rows", label: "Rows" },
          { key: "affected_matches", label: "Matches" },
          { key: "source_confirmation_needed", label: "Confirmation needed" },
          { key: "evidence", label: "Evidence" }
        ])}
      </section>
      <section class="card">
        <h3>Retained exclusions</h3>
        <div class="metric-list">
          <div class="metric-item"><span>Super Over groups</span><strong>${integer(superOvers.innings_groups)}</strong></div>
          <div class="metric-item"><span>Super Over deliveries</span><strong>${integer(superOvers.delivery_rows)}</strong></div>
          <div class="metric-item"><span>Revised-condition matches</span><strong>${integer(revised.matches)}</strong></div>
        </div>
        <p class="note">Revised-condition matches are excluded because effective-target delivery timing is unavailable.</p>
      </section>
    </div>
    ${sectionTitle("Audit findings")}
    ${tableCard("Diagnostics", findings, [
      { key: "code", label: "Finding" },
      { key: "severity", label: "Severity" },
      { key: "message", label: "Details" }
    ])}
    ${sectionTitle("Detected columns")}
    <div>${schemaGroups}</div>
    ${sectionTitle("Assumptions")}
    <section class="card">
      <p class="muted">Configured choices used in the saved exploratory run. These are not treated as source-confirmed definitions.</p>
      <div class="metric-list">${(quality.assumptions || []).map((item) => `
        <div class="metric-item"><span>${escapeHtml(item.name || item.gate_id || "Assumption")}</span><strong>${escapeHtml(item.value ?? item.status ?? "Configured")}</strong></div>`).join("") || `<p class="muted">Detailed assumption rows are not available.</p>`}</div>
      <hr class="section-divider">
      <h3>Run provenance</h3>
      <div class="metric-list">
        <div class="metric-item"><span>Run ID</span><strong>${escapeHtml(dashboardData.manifest.run_id)}</strong></div>
        <div class="metric-item"><span>Completed</span><strong>${escapeHtml(dateLabel(dashboardData.manifest.completed_at))}</strong></div>
        <div class="metric-item"><span>Configuration version</span><strong>${escapeHtml(dashboardData.manifest.config_version || "—")}</strong></div>
        <div class="metric-item"><span>Pressure assessment</span><strong>${escapeHtml(dashboardData.manifest.pressure_validation.status || "—")}</strong></div>
      </div>
      <button class="button secondary" id="download-audit-json" style="margin-top:15px">Download published diagnostics JSON</button>
    </section>
    <p class="note">Only aggregate diagnostics, rankings, and match/phase profile summaries are included here; raw input CSVs and delivery-level records are not published.</p>`;
  document.getElementById("download-audit-json").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(quality, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "source_diagnostics.json";
    link.click();
    URL.revokeObjectURL(url);
  });
}

function renderPage(page) {
  currentPage = page;
  sectionName.textContent = pageNames[page] || pageNames.overview;
  navButtons.forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  sidebar.classList.remove("open");
  menuButton.setAttribute("aria-expanded", "false");
  if (page === "overview") renderOverview();
  else if (page === "batting") renderRankingPage("batter");
  else if (page === "bowling") renderRankingPage("bowler");
  else if (page === "insights") renderInsights();
  else if (page === "players") renderPlayers();
  else if (page === "pressure") renderPressure();
  else if (page === "technical") renderRankingPage("batter", true);
  else if (page === "robustness") renderRobustness();
  else renderQuality();
}

function bindNavigation() {
  navButtons.forEach((button) => {
    button.addEventListener("click", () => renderPage(button.dataset.page));
  });
  pageRoot.addEventListener("click", (event) => {
    const target = event.target.closest("[data-go], [data-download]");
    if (!target) return;
    if (target.dataset.go) {
      renderPage(target.dataset.go);
      return;
    }
    const key = target.dataset.download;
    if (key === "batter_sensitivity" || key === "bowler_sensitivity"
      || key === "scenario_stability" || key === "bootstrap_results"
      || key === "batter_bootstrap_summary" || key === "bowler_bootstrap_summary"
      || key === "stability_adjusted_top10") {
      downloadCsv(`${key}.csv`, dashboardData.robustness[key]);
    }
  });
  menuButton.addEventListener("click", () => {
    const isOpen = sidebar.classList.toggle("open");
    menuButton.setAttribute("aria-expanded", String(isOpen));
  });
}

async function start() {
  bindNavigation();
  try {
    const response = await fetch("./data/dashboard.json");
    if (!response.ok) throw new Error(`Could not load dashboard data (${response.status}).`);
    dashboardData = await response.json();
    document.getElementById("sidebar-run").textContent =
      `Run ${dashboardData.manifest.run_id} · ${dateLabel(dashboardData.manifest.completed_at)}`;
    renderPage(currentPage);
  } catch (error) {
    pageRoot.innerHTML = `
      <div class="error-card">
        <div><strong>Dashboard data is unavailable.</strong><p>${escapeHtml(error.message)}</p><p class="note">Serve this site over HTTP(S) so the browser can load its adjacent JSON file.</p></div>
      </div>`;
  }
}

start();
