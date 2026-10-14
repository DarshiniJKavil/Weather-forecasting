const $ = (id) => document.getElementById(id);
const REFRESH_MS = 5 * 60 * 1000; // pull fresh live data every 5 minutes
const state = { data: null, unit: "C", selected: 0, chart: null, demo: false, nextRefresh: 0 };

const conv = (c) => (state.unit === "C" ? c : (c * 9) / 5 + 32);
const fmt = (c) => (c == null ? "--" : `${Math.round(conv(c))}°`);
const parseDate = (s) => new Date(s.slice(0, 10) + "T12:00:00");
const dow = (s, i) => (i === 0 ? "Today" : parseDate(s).toLocaleDateString(undefined, { weekday: "short" }));
const delta = (c) => (state.unit === "C" ? c : (c * 9) / 5);

// ---------- animated rain for rainy themes ----------
(function makeRain() {
  const box = $("rain");
  for (let i = 0; i < 70; i++) {
    const d = document.createElement("span");
    d.className = "drop";
    d.style.left = Math.random() * 100 + "%";
    d.style.animationDuration = 0.6 + Math.random() * 0.7 + "s";
    d.style.animationDelay = -Math.random() * 2 + "s";
    d.style.opacity = 0.3 + Math.random() * 0.6;
    box.appendChild(d);
  }
})();

// ---------- loading / errors ----------
let loadTimer;
function setLoading(on) {
  $("loading").hidden = !on;
  clearInterval(loadTimer);
  if (on) {
    $("content").hidden = true;
    $("error").hidden = true;
    const steps = ["Fetching live weather…", "Learning this city's forecast errors…", "Correcting the forecast…"];
    let i = 0;
    $("loadingText").textContent = steps[0];
    loadTimer = setInterval(() => ($("loadingText").textContent = steps[Math.min(++i, steps.length - 1)]), 2500);
  }
}

function showError(msg, canDemo) {
  $("errorText").textContent = msg;
  $("demoBtn").hidden = !canDemo;
  $("error").hidden = false;
}

async function load({ silent = false, demo = false } = {}) {
  const city = $("city").value.trim();
  if (!city) return;
  state.demo = demo;
  if (!silent) setLoading(true);
  try {
    const res = await fetch(`/api/forecast?city=${encodeURIComponent(city)}${demo ? "&demo=1" : ""}`);
    const json = await res.json();
    if (!res.ok) throw Object.assign(new Error(json.error || "Something went wrong"), { canDemo: json.can_demo });
    const keep = silent && state.data && state.data.location.name === json.location.name;
    state.data = json;
    if (!keep) state.selected = 0;
    setLoading(false);
    $("error").hidden = true;
    $("content").hidden = false;
    state.nextRefresh = Date.now() + REFRESH_MS;
    render();
  } catch (e) {
    if (silent) { $("updated").textContent = "Couldn't refresh. Will retry shortly."; state.nextRefresh = Date.now() + 60000; return; }
    setLoading(false);
    showError(e.message, e.canDemo);
  }
}

// ---------- rendering ----------
function render() {
  const { data } = state;
  const f = data.forecast, today = f[0], live = data.live;
  document.body.dataset.theme = live ? live.theme : today.theme;

  $("place").textContent = `${data.location.name}${data.location.country ? ", " + data.location.country : ""}`;
  const stamp = data.local_time ? new Date(data.local_time) : new Date();
  $("todayDate").textContent = stamp.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) +
    (data.local_time ? " · " + stamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + " local" : "");

  $("heroIcon").textContent = live ? live.icon : today.icon;
  $("heroTemp").textContent = live ? fmt(live.temp) : fmt((today.tmax + today.tmin) / 2);
  $("heroCond").textContent = live
    ? `${live.label} · feels like ${fmt(live.feels)}`
    : `${today.label} (model estimate)`;
  $("heroHL").textContent = `${fmt(today.tmax)} / ${fmt(today.tmin)}`;
  $("heroRain").textContent = `${today.rain_prob}%`;
  $("heroHum").textContent = live ? `${live.humidity}%` : "n/a";
  $("heroWind").textContent = live ? `${Math.round(live.wind)} km/h` : "n/a";

  const badge = $("modeBadge"), pill = $("livePill");
  const modeText = {
    mos: "Forecast: live official model + ML correction",
    blend: "Forecast: live official model blended with ML (limited history)",
    demo: "Demo mode: offline sample data, not real weather",
  }[data.mode];
  badge.textContent = modeText; badge.hidden = false;
  pill.classList.toggle("demo", data.mode === "demo");
  $("liveText").textContent = data.mode === "demo" ? "DEMO DATA" : "LIVE";

  renderHourly();
  renderCards();
  renderDetail();
  renderMetrics();
  renderChart();
  tickUpdated();
}

function tickUpdated() {
  if (!state.data) return;
  const t = new Date(state.data.updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (state.data.mode === "demo") { $("updated").textContent = `Generated ${t}`; return; }
  const left = Math.max(0, Math.round((state.nextRefresh - Date.now()) / 1000));
  $("updated").textContent = `Updated ${t} · auto-refresh in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
}

function renderHourly() {
  const h = state.data.hourly;
  $("hourlyPanel").hidden = !h.length;
  $("hourly").innerHTML = h.map((x, i) => {
    const hr = new Date(x.time).toLocaleTimeString([], { hour: "numeric" });
    return `<div class="hour${i === 0 ? " now" : ""}"><span>${i === 0 ? "Now" : hr}</span><b>${fmt(x.temp)}</b><em>💧${x.rain_prob ?? 0}%</em></div>`;
  }).join("");
}

function renderCards() {
  const box = $("cards");
  box.innerHTML = "";
  state.data.forecast.slice(0, +$("days").value).forEach((d, i) => {
    const b = document.createElement("button");
    b.className = "card" + (i === state.selected ? " active" : "");
    b.style.animationDelay = i * 60 + "ms";
    b.innerHTML = `<div class="dow">${dow(d.date, i)}</div>
      <div class="dt">${parseDate(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</div>
      <div class="ic">${d.icon}</div>
      <div class="hi">${fmt(d.tmax)}</div><div class="lo">${fmt(d.tmin)}</div>
      <div class="rn">💧 ${d.rain_prob}%</div>`;
    b.onclick = () => { state.selected = i; renderCards(); renderDetail(); };
    box.appendChild(b);
  });
}

function renderDetail() {
  const d = state.data.forecast[Math.min(state.selected, state.data.forecast.length - 1)];
  const cell = (label, val, sub = "") => `<div class="d"><span>${label}</span><b>${val}</b>${sub ? `<i>${sub}</i>` : ""}</div>`;
  const o = d.official, p = d.pattern;
  const sign = (v) => (v >= 0 ? "+" : "") + delta(v).toFixed(1) + "°";
  $("detail").innerHTML = `<h3>${d.icon} ${parseDate(d.date).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })} · ${d.label}</h3>
    ${cell("SkyCast high", fmt(d.tmax), `±${delta(d.band).toFixed(1)}° uncertainty`)}
    ${cell("SkyCast low", fmt(d.tmin))}
    ${cell("Rain chance", d.rain_prob + "%", `expected ${d.rain_mm} mm`)}
    ${o ? cell("Official model high", fmt(o.tmax), `low ${fmt(o.tmin)} · rain ${o.rain_prob ?? "n/a"}%`) : ""}
    ${o ? cell("ML correction", sign(d.tmax - o.tmax), "applied to the official high") : ""}
    ${p ? cell("Pattern-only ML high", fmt(p.tmax), "from past 7 days only") : ""}`;
}

function renderMetrics() {
  const m = state.data.metrics, u = state.unit === "C" ? 1 : 9 / 5;
  $("metricHint").textContent = `Scored on the latest ${m.test_days} days the model had not seen.`;
  const f = (v) => (v * u).toFixed(2) + "°";
  const cell = (label, val, good) => `<div class="metric ${good ? "good" : ""}"><span>${label}</span><b>${val}</b></div>`;
  $("metrics").innerHTML = state.data.mode === "mos"
    ? cell("Official model high error", f(m.raw_mae_tmax)) +
      cell("After ML correction", f(m.mos_mae_tmax), m.mos_mae_tmax < m.raw_mae_tmax) +
      cell("Official model low error", f(m.raw_mae_tmin)) +
      cell("After ML correction", f(m.mos_mae_tmin), m.mos_mae_tmin < m.raw_mae_tmin) +
      cell("Rain right/wrong: official", m.raw_rain_acc + "%") +
      cell("Rain right/wrong: corrected", m.mos_rain_acc + "%", m.mos_rain_acc > m.raw_rain_acc)
    : cell("High-temp error", f(m.mae_tmax), m.mae_tmax < m.baseline_mae_tmax) +
      cell("Low-temp error", f(m.mae_tmin)) +
      cell('"Same as yesterday" baseline', f(m.baseline_mae_tmax)) +
      cell("Rain right/wrong", m.rain_accuracy + "%");
  const imp = state.data.importance;
  $("importance").innerHTML = Object.entries(imp).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<div class="bar-row"><div><span>${k}</span><span>${Math.round(v * 100)}%</span></div><div class="bar"><i data-w="${v * 100}"></i></div></div>`).join("");
  requestAnimationFrame(() => document.querySelectorAll(".bar i").forEach((el) => (el.style.width = el.dataset.w + "%")));
}

function renderChart() {
  const { history, forecast } = state.data;
  const n = +$("days").value;
  const hist = history.slice(-14), fc = forecast.slice(0, n);
  const labels = [...hist, ...fc].map((d) => parseDate(d.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }));
  const pad = (a, before) => (before ? [...Array(hist.length).fill(null), ...a] : [...a, ...Array(fc.length).fill(null)]);
  const histHi = pad(hist.map((d) => conv(d.tmax)), false);
  const fcHi = [...Array(hist.length - 1).fill(null), conv(hist.at(-1).tmax), ...fc.map((d) => conv(d.tmax))];
  const fcLo = pad(fc.map((d) => conv(d.tmin)), true);
  const official = pad(fc.map((d) => (d.official ? conv(d.official.tmax) : null)), true);
  const upper = pad(fc.map((d) => conv(d.tmax) + delta(d.band)), true);
  const lower = pad(fc.map((d) => conv(d.tmax) - delta(d.band)), true);
  const rain = [...hist.map((d) => d.rain_mm), ...fc.map((d) => d.rain_mm)];

  const ctx = $("chart").getContext("2d");
  if (state.chart) state.chart.destroy();
  const grid = "rgba(255,255,255,.1)", tick = "rgba(255,255,255,.7)";
  Chart.defaults.font.family = "Inter";
  const datasets = [
    { type: "bar", label: "Rain (mm)", data: rain, yAxisID: "y2", backgroundColor: "rgba(125,211,252,.35)", borderRadius: 4, order: 5 },
    { type: "line", label: "Band top", data: upper, borderWidth: 0, pointRadius: 0, fill: false, order: 4 },
    { type: "line", label: "Uncertainty", data: lower, borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(251,191,36,.2)", fill: "-1", order: 4 },
    { type: "line", label: "Past high", data: histHi, borderColor: "#e2e8f0", backgroundColor: "#e2e8f0", tension: 0.35, pointRadius: 3, order: 2 },
    { type: "line", label: "SkyCast high", data: fcHi, borderColor: "#fbbf24", backgroundColor: "#fbbf24", borderDash: [6, 4], tension: 0.35, pointRadius: 4, order: 1 },
    { type: "line", label: "SkyCast low", data: fcLo, borderColor: "#38bdf8", backgroundColor: "#38bdf8", borderDash: [6, 4], tension: 0.35, pointRadius: 4, order: 1 },
  ];
  if (official.some((v) => v !== null))
    datasets.push({ type: "line", label: "Official model high", data: official, borderColor: "#f472b6", backgroundColor: "#f472b6", borderWidth: 1.5, tension: 0.35, pointRadius: 2, order: 3 });
  state.chart = new Chart(ctx, {
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: tick, usePointStyle: true, filter: (i) => i.text !== "Band top" } },
        tooltip: { filter: (i) => i.dataset.label !== "Band top" && i.raw !== null },
      },
      scales: {
        x: { ticks: { color: tick, maxRotation: 0, autoSkip: true }, grid: { display: false } },
        y: { ticks: { color: tick, callback: (v) => v + "°" }, grid: { color: grid } },
        y2: { position: "right", beginAtZero: true, suggestedMax: 40, ticks: { color: tick }, grid: { display: false }, title: { display: true, text: "mm", color: tick } },
      },
    },
  });
}

// ---------- events ----------
$("searchForm").addEventListener("submit", (e) => { e.preventDefault(); load(); });
$("chips").addEventListener("click", (e) => {
  if (e.target.tagName === "BUTTON") { $("city").value = e.target.textContent; load(); }
});
$("demoBtn").addEventListener("click", () => load({ demo: true }));
$("refreshBtn").addEventListener("click", () => { $("updated").textContent = "Refreshing…"; load({ silent: true, demo: state.demo }); });
$("days").addEventListener("input", (e) => {
  $("daysVal").textContent = e.target.value;
  if (!state.data) return;
  state.selected = Math.min(state.selected, +e.target.value - 1);
  renderCards(); renderDetail(); renderChart();
});
for (const u of ["C", "F"]) {
  $("unit" + u).addEventListener("click", () => {
    state.unit = u;
    $("unitC").classList.toggle("active", u === "C");
    $("unitF").classList.toggle("active", u === "F");
    if (state.data) render();
  });
}

// live clock + automatic refresh
setInterval(() => {
  if (!state.data || state.demo) return;
  tickUpdated();
  if (Date.now() >= state.nextRefresh) { state.nextRefresh = Date.now() + REFRESH_MS; load({ silent: true }); }
}, 1000);

load();
