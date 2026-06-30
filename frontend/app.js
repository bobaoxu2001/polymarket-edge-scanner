"use strict";

// --------------------------- tiny helpers ---------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.status === 204 ? null : res.json();
}

const money = (v) =>
  (v < 0 ? "-$" : "$") +
  Math.abs(v ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
const money2 = (v) =>
  (v < 0 ? "-$" : "$") +
  Math.abs(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v) => `${((v ?? 0) * 100).toFixed(1)}%`;
const signed = (v) => `${v >= 0 ? "+" : ""}${(v ?? 0).toFixed(3)}`;
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const esc = (s) =>
  (s ?? "").toString().replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function actionPill(action) {
  const map = {
    "PAPER BUY YES": ["buy-yes", "BUY YES"],
    "PAPER BUY NO": ["buy-no", "BUY NO"],
    WATCH: ["watch", "WATCH"],
    AVOID: ["avoid", "AVOID"],
  };
  const [c, label] = map[action] || ["avoid", action];
  return `<span class="pill ${c}">${label}</span>`;
}
function statusPill(s) {
  const map = {
    OPEN: ["open", "OPEN"],
    RESOLVED_WIN: ["win", "WIN"],
    RESOLVED_LOSS: ["loss", "LOSS"],
    CLOSED: ["closed", "CLOSED"],
    CANCELLED: ["cancelled", "CANCELLED"],
  };
  const [c, label] = map[s] || ["closed", s];
  return `<span class="pill ${c}">${label}</span>`;
}
const confLabel = (c) => (c >= 0.66 ? "HIGH" : c >= 0.4 ? "MED" : "LOW");

// --------------------------- overview cards -------------------------------
async function loadOverview() {
  let m;
  try {
    m = await api("/api/metrics/overview");
  } catch {
    return;
  }
  $("#last-scan").textContent = m.last_scan_at
    ? "last scan: " + new Date(m.last_scan_at + "Z").toLocaleTimeString()
    : "last scan: —";
  const cards = [
    ["Markets scanned", m.active_markets_scanned, ""],
    ["Opportunities", m.opportunities_found, ""],
    ["Open trades", m.open_paper_trades, ""],
    ["Bankroll", money(m.paper_bankroll), ""],
    ["Equity", money2(m.equity), ""],
    ["Paper PnL", money2(m.paper_pnl), cls(m.paper_pnl)],
    ["ROI", pct(m.roi), cls(m.roi)],
    ["Avg edge", signed(m.average_edge), cls(m.average_edge)],
  ];
  $("#overview-cards").innerHTML = cards
    .map(
      ([label, val, c]) =>
        `<div class="card"><div class="label">${label}</div><div class="value ${c}">${val}</div></div>`
    )
    .join("");
}

// --------------------------- opportunities --------------------------------
async function loadCategories() {
  try {
    const cats = await api("/api/opportunities/categories");
    const sel = $("#opp-category");
    const cur = sel.value;
    sel.innerHTML =
      '<option value="">All</option>' +
      cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    sel.value = cur;
  } catch {}
}

async function loadOpportunities() {
  const cat = $("#opp-category").value;
  const sort = $("#opp-sort").value;
  const actionable = $("#opp-actionable").checked;
  const qs = new URLSearchParams({ sort, limit: "200" });
  if (cat) qs.set("category", cat);
  if (actionable) qs.set("actionable_only", "true");

  let rows;
  try {
    rows = await api(`/api/opportunities?${qs}`);
  } catch {
    return;
  }
  const tbody = $("#opp-table tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="muted center">No opportunities — run a scan.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((o) => {
      const ask = o.best_side === "NO" ? o.ask_no : o.ask_yes;
      return `<tr class="clickable" data-id="${esc(o.market_id)}">
        <td class="market-cell">${esc(o.question)}</td>
        <td>${esc(o.category)}</td>
        <td>${o.best_side ?? "—"}</td>
        <td class="num">${ask.toFixed(3)}</td>
        <td class="num">${pct(o.fair_prob_yes)}</td>
        <td class="num ${cls(o.best_edge)}">${signed(o.best_edge)}</td>
        <td class="num">${o.spread.toFixed(3)}</td>
        <td class="num">${money(o.liquidity)}</td>
        <td class="num">${(o.confidence * 100).toFixed(0)} <span class="muted">${confLabel(o.confidence)}</span></td>
        <td>${actionPill(o.action)}</td>
        <td class="reason-cell">${esc(o.reason)}</td>
      </tr>`;
    })
    .join("");
  $$("#opp-table tbody tr.clickable").forEach((tr) =>
    tr.addEventListener("click", () => openDetail(tr.dataset.id))
  );
}

// --------------------------- paper trades ---------------------------------
async function loadTrades() {
  const status = $("#trade-status").value;
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  let rows;
  try {
    rows = await api(`/api/paper-trades?${qs}`);
  } catch {
    return;
  }
  const tbody = $("#trade-table tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="muted center">No paper trades yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((t) => {
      const pnl = t.status === "OPEN" ? t.unrealized_pnl : t.realized_pnl;
      const actions =
        t.status === "OPEN"
          ? `<button class="btn btn-sm" data-close="${t.id}">Close</button>
             <button class="btn btn-sm" data-cancel="${t.id}">Cancel</button>`
          : "";
      return `<tr>
        <td class="num">${new Date(t.opened_at + "Z").toLocaleDateString()}</td>
        <td class="market-cell">${esc(t.market_title)}<br><span class="muted">${t.outcome}</span></td>
        <td>${t.outcome.toUpperCase()}</td>
        <td class="num">${t.entry_price.toFixed(3)}</td>
        <td class="num">${money2(t.size_usd)}</td>
        <td class="num">${t.current_value != null ? money2(t.current_value) : "—"}</td>
        <td>${statusPill(t.status)}</td>
        <td class="num ${cls(pnl)}">${pnl != null ? money2(pnl) : "—"}</td>
        <td class="reason-cell">${esc(t.reason)}</td>
        <td>${actions}</td>
      </tr>`;
    })
    .join("");
  $$("#trade-table [data-close]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/paper-trades/${b.dataset.close}/close`, { method: "POST" });
      refreshAll();
    })
  );
  $$("#trade-table [data-cancel]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/paper-trades/${b.dataset.cancel}/cancel`, { method: "POST" });
      refreshAll();
    })
  );
}

// --------------------------- metrics --------------------------------------
async function loadMetrics() {
  let m;
  try {
    m = await api("/api/metrics/evaluation");
  } catch {
    return;
  }
  const summary = [
    ["Signals", m.num_signals],
    ["Paper trades", m.num_paper_trades],
    ["Resolved", m.num_resolved],
    ["Win rate", pct(m.win_rate)],
    ["Avg edge", signed(m.average_edge)],
    ["Avg return", pct(m.average_realized_return)],
    ["ROI", pct(m.roi)],
    ["Brier", m.brier_score != null ? m.brier_score.toFixed(3) : "—"],
  ];
  $("#eval-summary").innerHTML = summary
    .map(([l, v]) => `<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`)
    .join("");

  $("#calib-table tbody").innerHTML =
    m.calibration.map(
      (b) => `<tr><td>${b.bucket}</td><td class="num">${pct(b.predicted_prob)}</td>
        <td class="num">${pct(b.actual_win_rate)}</td><td class="num">${b.count}</td></tr>`
    ).join("") || `<tr><td colspan="4" class="muted center">No resolved trades yet.</td></tr>`;

  $("#cat-table tbody").innerHTML =
    m.profit_by_category.map(
      (c) => `<tr><td>${esc(c.category)}</td><td class="num ${cls(c.realized_pnl)}">${money2(c.realized_pnl)}</td>
        <td class="num">${c.trades}</td></tr>`
    ).join("") || `<tr><td colspan="3" class="muted center">—</td></tr>`;

  $("#conf-table tbody").innerHTML =
    m.profit_by_confidence.map(
      (c) => `<tr><td>${c.confidence_level}</td><td class="num ${cls(c.realized_pnl)}">${money2(c.realized_pnl)}</td>
        <td class="num">${c.trades}</td><td class="num">${pct(c.win_rate)}</td></tr>`
    ).join("") || `<tr><td colspan="4" class="muted center">—</td></tr>`;
}

// --------------------------- arbitrage ------------------------------------
async function loadArbitrage() {
  const arbOnly = $("#arb-only").checked;
  const tbody = $("#arb-table tbody");
  tbody.innerHTML = `<tr><td colspan="9" class="muted center">Scanning order books…</td></tr>`;
  let rows;
  try {
    rows = await api(`/api/arbitrage?limit=20&arb_only=${arbOnly}`);
  } catch {
    tbody.innerHTML = `<tr><td colspan="9" class="muted center">Scan failed.</td></tr>`;
    return;
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="muted center">No ${arbOnly ? "arbitrage" : "results"} found (expected — markets are efficient).</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((a) => {
      const status = a.is_arbitrage
        ? `<span class="pill win">ARB ${signed(a.arb_edge)}</span>`
        : `<span class="pill avoid">none</span>`;
      return `<tr>
        <td class="market-cell">${esc(a.question)}</td>
        <td>${esc(a.category)}</td>
        <td class="num">${a.ask_yes != null ? a.ask_yes.toFixed(3) : "—"}</td>
        <td class="num">${a.ask_no != null ? a.ask_no.toFixed(3) : "—"}</td>
        <td class="num">${a.cost != null ? a.cost.toFixed(3) : "—"}</td>
        <td class="num ${a.overround != null ? cls(-a.overround) : ""}">${a.overround != null ? signed(a.overround) : "—"}</td>
        <td class="num ${a.arb_edge != null ? cls(a.arb_edge) : ""}">${a.arb_edge != null ? signed(a.arb_edge) : "—"}</td>
        <td class="num">${a.executable_shares != null ? a.executable_shares : "—"}</td>
        <td>${status}</td>
      </tr>`;
    })
    .join("");
}
$("#arb-scan-btn").addEventListener("click", async () => {
  const btn = $("#arb-scan-btn");
  btn.disabled = true;
  btn.textContent = "Scanning…";
  await loadArbitrage();
  btn.disabled = false;
  btn.textContent = "⟳ Scan order books";
});
$("#arb-only").addEventListener("change", loadArbitrage);

// --------------------------- settings -------------------------------------
async function loadSettings() {
  let s;
  try {
    s = await api("/api/settings");
  } catch {
    return;
  }
  const f = $("#settings-form");
  f.paper_trading_enabled.checked = s.paper_trading_enabled;
  f.allow_extreme_prices.checked = s.allow_extreme_prices;
  f.paper_bankroll.value = s.paper_bankroll;
  f.min_liquidity.value = s.min_liquidity;
  f.min_volume_24h.value = s.min_volume_24h;
  f.max_spread.value = s.max_spread;
  f.min_edge_to_trade.value = s.min_edge_to_trade;
  f.safety_margin.value = s.safety_margin;
  f.estimated_fee.value = s.estimated_fee;
  f.max_days_to_resolution.value = s.max_days_to_resolution;
  f.categories_filter.value = (s.categories_filter || []).join(", ");
  $("#paper-badge").textContent = s.paper_trading_enabled ? "PAPER MODE" : "PAPER PAUSED";
}

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const cats = f.categories_filter.value
    .split(",").map((x) => x.trim()).filter(Boolean);
  const payload = {
    paper_trading_enabled: f.paper_trading_enabled.checked,
    allow_extreme_prices: f.allow_extreme_prices.checked,
    paper_bankroll: parseFloat(f.paper_bankroll.value),
    min_liquidity: parseFloat(f.min_liquidity.value),
    min_volume_24h: parseFloat(f.min_volume_24h.value),
    max_spread: parseFloat(f.max_spread.value),
    min_edge_to_trade: parseFloat(f.min_edge_to_trade.value),
    safety_margin: parseFloat(f.safety_margin.value),
    estimated_fee: parseFloat(f.estimated_fee.value),
    max_days_to_resolution: parseInt(f.max_days_to_resolution.value, 10),
    categories_filter: cats,
  };
  $("#settings-status").textContent = "Saving…";
  try {
    await api("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
    $("#settings-status").textContent = "Saved ✓";
    loadSettings();
  } catch {
    $("#settings-status").textContent = "Error saving";
  }
});

// --------------------------- market detail --------------------------------
async function openDetail(id) {
  const modal = $("#detail-modal");
  const content = $("#detail-content");
  content.innerHTML = `<p class="muted">Loading…</p>`;
  modal.classList.remove("hidden");
  let d;
  try {
    d = await api(`/api/markets/${id}`);
  } catch {
    content.innerHTML = `<p class="muted">Failed to load market.</p>`;
    return;
  }
  const m = d.market;
  const b = d.model_breakdown;
  const ob = d.orderbook;
  const sig = (b && b.signals_available) || {};
  const sigRow = Object.entries(sig)
    .map(([k, v]) => `${k}: ${v ? "✓" : "—"}`).join(" &nbsp; ");

  const breakdownHtml = b
    ? `<div class="kv">
        <div class="k">Implied (market)</div><div>${pct(b.implied_prob_yes)}</div>
        <div class="k">Calibrated market</div><div>${pct(b.calibrated_market_prob)}</div>
        <div class="k">External signal</div><div>${b.external_prob != null ? pct(b.external_prob) : "unavailable"}</div>
        <div class="k">Microstructure</div><div>${b.micro_prob != null ? pct(b.micro_prob) : "unavailable"}</div>
        <div class="k">News signal</div><div>${b.news_prob != null ? pct(b.news_prob) : "unavailable"}</div>
        <div class="k"><strong>Fair probability</strong></div><div><strong>${pct(b.fair_prob_yes)}</strong></div>
      </div>
      <div class="bar"><span style="width:${(b.fair_prob_yes * 100).toFixed(0)}%"></span></div>
      <p class="note">Signals available — ${sigRow}</p>
      ${(b.notes || []).map((n) => `<p class="note">• ${esc(n)}</p>`).join("")}`
    : "<p class='muted'>No model output.</p>";

  const obHtml = ob
    ? `<div class="kv">
        <div class="k">Best bid / ask</div><div>${ob.best_bid ?? "—"} / ${ob.best_ask ?? "—"}</div>
        <div class="k">Spread</div><div>${ob.spread ?? "—"}</div>
        <div class="k">Top-5 depth (bid/ask)</div><div>${ob.bid_depth_top5} / ${ob.ask_depth_top5}</div>
        <div class="k">Imbalance</div><div>${ob.imbalance ?? "—"}</div>
      </div>`
    : "<p class='muted'>Order book unavailable.</p>";

  content.innerHTML = `
    <h2 style="margin-top:0">${esc(m.question)}</h2>
    <div class="kv">
      <div class="k">Category</div><div>${esc(m.category)}</div>
      <div class="k">End date</div><div>${m.end_date ? new Date(m.end_date + "Z").toLocaleString() : "—"}</div>
      <div class="k">Outcomes</div><div>${(m.outcomes || []).join(" / ")} @ ${(m.outcome_prices || []).map((p) => p.toFixed(3)).join(" / ")}</div>
      <div class="k">Liquidity / 24h vol</div><div>${money(m.liquidity)} / ${money(m.volume_24h)}</div>
    </div>
    <hr class="section-divider" />
    <h3>Model breakdown</h3>${breakdownHtml}
    <hr class="section-divider" />
    <h3>Order book</h3>${obHtml}
    <hr class="section-divider" />
    <h3>Risk notes</h3>${(d.risk_notes || []).map((n) => `<p class="note">• ${esc(n)}</p>`).join("")}
    <hr class="section-divider" />
    <h3>Resolution rules</h3>
    <p class="note" style="white-space:pre-wrap">${esc((m.description || "").slice(0, 1200))}</p>`;
}
$("#modal-close").addEventListener("click", () => $("#detail-modal").classList.add("hidden"));
$("#detail-modal").addEventListener("click", (e) => {
  if (e.target.id === "detail-modal") $("#detail-modal").classList.add("hidden");
});

// --------------------------- tabs + refresh -------------------------------
let activeTab = "opportunities";
$$(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    activeTab = t.dataset.tab;
    $(`#tab-${activeTab}`).classList.add("active");
    loadActiveTab();
  })
);

function loadActiveTab() {
  if (activeTab === "opportunities") loadOpportunities();
  else if (activeTab === "trades") loadTrades();
  else if (activeTab === "metrics") loadMetrics();
  else if (activeTab === "settings") loadSettings();
}

function refreshAll() {
  loadOverview();
  loadCategories();
  loadActiveTab();
}

$("#scan-btn").addEventListener("click", async () => {
  const btn = $("#scan-btn");
  btn.disabled = true;
  btn.textContent = "Scanning…";
  try {
    await api("/api/scan", { method: "POST" });
  } catch {}
  btn.disabled = false;
  btn.textContent = "⟳ Scan now";
  refreshAll();
});

["opp-category", "opp-sort", "opp-actionable"].forEach((id) =>
  $(`#${id}`).addEventListener("change", loadOpportunities)
);
$("#trade-status").addEventListener("change", loadTrades);

// initial load + periodic refresh
refreshAll();
loadSettings();
setInterval(() => {
  loadOverview();
  if (activeTab !== "settings") loadActiveTab();
}, 20000);
