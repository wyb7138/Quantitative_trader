/* Quant Trader dashboard — frontend logic */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// ── helpers ──────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const fmtMoney = (n) =>
  "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = (n) => `${n >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`;
const signClass = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "zero");

let toastTimer;
function toast(msg, isErr = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
}

function busy(btn, on, label) {
  if (!btn) return;
  if (on) {
    btn.dataset.label = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${label || "Working…"}`;
  } else {
    btn.disabled = false;
    btn.textContent = btn.dataset.label || btn.textContent;
  }
}

function sigCell(v) {
  const cls = v > 0 ? "p" : v < 0 ? "n" : "z";
  const txt = v > 0 ? "+1" : v < 0 ? "−1" : "0";
  return `<td class="num"><span class="sig ${cls}">${txt}</span></td>`;
}

// ── tab switching ──────────────────────────────────────────────────────────
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $("#" + tab.dataset.tab).classList.add("active");
  });
});

// ── Dashboard / portfolio ──────────────────────────────────────────────────
function renderPortfolio(p) {
  const flag = $("#price-flag");
  if (p.prices_live) {
    flag.classList.add("hidden");
  } else {
    flag.textContent = "⚠ prices offline — using entry prices";
    flag.classList.remove("hidden");
  }

  $("#portfolio-cards").innerHTML = `
    <div class="card"><div class="label">Total Value</div><div class="value">${fmtMoney(p.total_value)}</div></div>
    <div class="card"><div class="label">Cash</div><div class="value sm">${fmtMoney(p.cash)}</div></div>
    <div class="card"><div class="label">Holdings</div><div class="value sm">${fmtMoney(p.holdings_value)}</div></div>
    <div class="card"><div class="label">Total Return</div><div class="value ${signClass(p.return_pct)}">${fmtPct(p.return_pct)}</div></div>
    <div class="card"><div class="label">Drawdown</div><div class="value ${signClass(p.drawdown_pct)}">${fmtPct(p.drawdown_pct)}</div></div>
  `;

  const tbody = $("#positions-table tbody");
  if (!p.positions.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No open positions.</td></tr>`;
    return;
  }
  tbody.innerHTML = p.positions
    .map(
      (pos) => `
    <tr>
      <td><strong>${pos.symbol}</strong></td>
      <td class="num">${pos.shares.toLocaleString()}</td>
      <td class="num">${fmtMoney(pos.entry_price)}</td>
      <td class="num">${fmtMoney(pos.price)}</td>
      <td class="num">${fmtMoney(pos.market_value)}</td>
      <td class="num ${signClass(pos.pnl_pct)}">${fmtPct(pos.pnl_pct)}</td>
    </tr>`
    )
    .join("");
}

async function loadPortfolio() {
  try {
    renderPortfolio(await api("/api/portfolio"));
  } catch (e) {
    toast(e.message, true);
  }
}

$("#refresh-portfolio").addEventListener("click", loadPortfolio);
$("#run-tick").addEventListener("click", async (e) => {
  busy(e.target, true, "Running…");
  try {
    renderPortfolio(await api("/api/paper/tick", { method: "POST" }));
    toast("Paper tick executed.");
  } catch (err) {
    toast(err.message, true);
  } finally {
    busy(e.target, false);
  }
});

// ── Signals ────────────────────────────────────────────────────────────────
async function loadSignals(e) {
  const btn = e?.target;
  busy(btn, true, "Loading…");
  try {
    const syms = $("#signal-symbols").value.trim();
    const q = syms ? "?symbols=" + encodeURIComponent(syms) : "";
    const data = await api("/api/signals" + q);
    $("#signals-asof").textContent = data.error
      ? data.error
      : `As of ${data.as_of} · score ≥ ${data.threshold} opens a long`;
    const tbody = $("#signals-table tbody");
    if (!data.signals.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="8">No signals available.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.signals
      .map((s) => {
        const pill = s.flag === "BUY"
          ? `<span class="pill buy">BUY</span>`
          : s.flag === "SELL"
          ? `<span class="pill sell">SELL</span>`
          : "";
        return `<tr>
          <td><strong>${s.symbol}</strong></td>
          <td class="num ${signClass(s.score)}"><strong>${s.score > 0 ? "+" : ""}${s.score}</strong></td>
          <td class="num">${fmtMoney(s.close)}</td>
          <td class="num">${s.rsi.toFixed(1)}</td>
          ${sigCell(s.rsi_sig)}${sigCell(s.bb_sig)}${sigCell(s.macd_sig)}
          <td>${pill}</td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    toast(err.message, true);
  } finally {
    busy(btn, false);
  }
}
$("#load-signals").addEventListener("click", loadSignals);

// ── Backtest ───────────────────────────────────────────────────────────────
let equityChart, drawdownChart;

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: "index", intersect: false },
  plugins: { legend: { labels: { color: "#d7dce5", usePointStyle: true } } },
  scales: {
    x: { ticks: { color: "#8b93a7", maxTicksLimit: 10 }, grid: { color: "#1b2230" } },
    y: { ticks: { color: "#8b93a7" }, grid: { color: "#1b2230" } },
  },
};

function renderMetrics(metrics) {
  const order = [
    "Total Return", "CAGR", "Sharpe Ratio", "Sortino Ratio",
    "Max Drawdown", "Calmar Ratio", "Buy & Hold Return", "Alpha (approx)",
    "Win Rate", "Total Trades", "Total PnL", "Stop Losses Hit",
  ];
  const keys = order.filter((k) => k in metrics).concat(
    Object.keys(metrics).filter((k) => !order.includes(k) && k !== "Period")
  );
  $("#metrics-cards").innerHTML = keys
    .map((k) => {
      const v = metrics[k];
      const cls = /^[+\-]/.test(String(v)) ? signClass(parseFloat(v)) : "";
      return `<div class="card"><div class="label">${k}</div><div class="value sm ${cls}">${v}</div></div>`;
    })
    .join("");
}

function renderEquityChart(eq) {
  const ctx = $("#equity-chart");
  equityChart?.destroy();
  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: eq.dates,
      datasets: [
        { label: "Strategy", data: eq.strategy, borderColor: "#4c8dff", backgroundColor: "rgba(76,141,255,0.08)", fill: true, pointRadius: 0, borderWidth: 1.8, tension: 0.05 },
        { label: "Buy & Hold", data: eq.buy_hold, borderColor: "#f5b942", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.4, tension: 0.05 },
      ],
    },
    options: {
      ...CHART_DEFAULTS,
      scales: {
        ...CHART_DEFAULTS.scales,
        y: { ...CHART_DEFAULTS.scales.y, ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: (v) => "$" + (v / 1000).toFixed(0) + "k" } },
      },
    },
  });
}

function renderDrawdownChart(eq) {
  const ctx = $("#drawdown-chart");
  drawdownChart?.destroy();
  drawdownChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: eq.dates,
      datasets: [
        { label: "Drawdown", data: eq.drawdown, borderColor: "#ff5d5d", backgroundColor: "rgba(255,93,93,0.18)", fill: true, pointRadius: 0, borderWidth: 1.2 },
      ],
    },
    options: {
      ...CHART_DEFAULTS,
      plugins: { legend: { display: false } },
      scales: {
        ...CHART_DEFAULTS.scales,
        y: { ...CHART_DEFAULTS.scales.y, ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: (v) => v.toFixed(0) + "%" } },
      },
    },
  });
}

function renderBtTrades(trades) {
  $("#bt-trade-count").textContent = trades.length ? `(${trades.length})` : "";
  const tbody = $("#bt-trades-table tbody");
  if (!trades.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No trades.</td></tr>`;
    return;
  }
  tbody.innerHTML = trades
    .map((t) => `
      <tr>
        <td>${t.date}</td>
        <td><strong>${t.symbol}</strong></td>
        <td>${actionPill(t.action)}</td>
        <td class="num">${t.shares.toLocaleString()}</td>
        <td class="num">${fmtMoney(t.price)}</td>
        <td class="num ${signClass(t.pnl)}">${t.pnl ? fmtMoney(t.pnl) : "—"}</td>
      </tr>`)
    .join("");
}

function actionPill(a) {
  if (a === "BUY") return `<span class="pill buy">BUY</span>`;
  if (a === "SELL") return `<span class="pill sell">SELL</span>`;
  if (a === "STOP_LOSS") return `<span class="pill stop">STOP</span>`;
  return a;
}

$("#backtest-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#backtest-form button");
  busy(btn, true, "Running…");
  $("#bt-status").textContent = "Fetching data and running backtest…";
  try {
    const body = JSON.stringify({
      symbols: $("#bt-symbols").value.trim(),
      start: $("#bt-start").value,
      end: $("#bt-end").value,
    });
    const data = await api("/api/backtest", { method: "POST", body });
    $("#bt-status").textContent = `${data.symbols.length} symbols · ${data.start} → ${data.end}`;
    renderMetrics(data.metrics);
    renderEquityChart(data.equity);
    renderDrawdownChart(data.equity);
    renderBtTrades(data.trades);
    $("#bt-results").classList.remove("hidden");
  } catch (err) {
    $("#bt-status").textContent = "";
    toast(err.message, true);
  } finally {
    busy(btn, false);
  }
});

// ── Trades history ─────────────────────────────────────────────────────────
function renderTradeStats(s) {
  $("#trade-stats").innerHTML = `
    <div class="card"><div class="label">Closed Trades</div><div class="value sm">${s.closed_trades}</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value sm">${(s.win_rate * 100).toFixed(1)}%</div></div>
    <div class="card"><div class="label">Total P&amp;L</div><div class="value sm ${signClass(s.total_pnl)}">${fmtMoney(s.total_pnl)}</div></div>
    <div class="card"><div class="label">Avg P&amp;L</div><div class="value sm ${signClass(s.avg_pnl)}">${fmtMoney(s.avg_pnl)}</div></div>
  `;
}

async function loadTrades(e) {
  const btn = e?.target;
  busy(btn, true, "Loading…");
  try {
    const sym = $("#trade-symbol").value.trim();
    const q = sym ? "?symbol=" + encodeURIComponent(sym) : "";
    const data = await api("/api/trades" + q);
    renderTradeStats(data.stats);
    const tbody = $("#trades-table tbody");
    if (!data.trades.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No trades recorded yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.trades
      .map((t) => `
        <tr>
          <td>${t.time || ""}</td>
          <td><strong>${t.symbol || ""}</strong></td>
          <td>${actionPill(t.action || "")}</td>
          <td class="num">${(t.shares || 0).toLocaleString()}</td>
          <td class="num">${fmtMoney(t.price || 0)}</td>
          <td class="num ${signClass(t.pnl || 0)}">${t.pnl ? fmtMoney(t.pnl) : "—"}</td>
        </tr>`)
      .join("");
  } catch (err) {
    toast(err.message, true);
  } finally {
    busy(btn, false);
  }
}
$("#load-trades").addEventListener("click", loadTrades);

// ── init ───────────────────────────────────────────────────────────────────
async function init() {
  try {
    const cfg = await api("/api/config");
    $("#bt-start").value = cfg.default_start;
    $("#bt-end").value = cfg.default_end;
    $("#bt-symbols").placeholder = `blank = full universe (${cfg.universe.length})`;
  } catch (_) { /* non-fatal */ }
  loadPortfolio();
  loadTrades();
}
init();
