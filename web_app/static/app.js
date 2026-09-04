/* OTA Sizing Explorer - wiring for the stitch_UI v2 design.
 * The server validates, guards (25% internal GBW), and verifies; this file
 * renders real data only. Unresolved/error states show no geometry. */
"use strict";

const $ = (id) => document.getElementById(id);

const DEFAULTS = { "min-gain": 35, "min-gbw": 100, "load-cap": 1, "max-power": 200 };
const PM_FLOOR = 45;            // verifier default (deg)
const GUARD = 1.25;             // tt-ideal-tail-gbw-v1

let current = null;             // last verified API response (enables export)
let pollTimer = null;

/* ------------------------------------------------------------ helpers -- */
function fmt(v, d) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  return Number(v).toLocaleString("en-US",
    { minimumFractionDigits: d, maximumFractionDigits: d });
}

function signed(v, d, unit) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return (n >= 0 ? "+" : "−") + fmt(Math.abs(n), d) + (unit ? " " + unit : "");
}

function esc(s) {
  return String(s).replace(/[&<>"']/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* -------------------------------------------------------------- health -- */
function applyHealth(h) {
  const pill = $("engine-pill"), text = $("engine-text");
  const core = $("engine-dot-core"), ping = $("engine-ping");
  const wave = $("engine-wave");
  const bDot = $("backend-dot"), bPing = $("backend-ping"), bText = $("backend-text");
  const strip = $("strip-engine-text");
  pill.className = "hidden sm:flex items-center gap-2.5 px-3.5 py-1.5 rounded-full text-xs font-mono font-medium shadow-2xs ";
  if (h.state === "ready") {
    text.textContent = "Engine Ready";
    strip.textContent = "LUT Engine Online";
    pill.classList.add("bg-emerald-50/90", "border-emerald-200/90", "text-emerald-800");
    core.className = "relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500";
    ping.className = "animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75";
    wave.classList.remove("hidden");
    wave.classList.add("text-emerald-600", "chip-glow-pulse");
    bDot.className = "relative inline-flex rounded-full h-2 w-2 bg-cyan-500";
    bPing.className = "animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75";
    bText.textContent = "Spectre LUT Backend Online";
  } else if (h.state === "loading") {
    text.textContent = "Engine Loading";
    strip.textContent = "LUT Engine Loading";
    pill.classList.add("bg-amber-50", "border-amber-200", "text-amber-800");
    core.className = "relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500";
    ping.className = "animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75";
    wave.classList.add("hidden");
    bDot.className = "relative inline-flex rounded-full h-2 w-2 bg-amber-500";
    bPing.className = "hidden";
    bText.textContent = "Spectre LUT Backend Loading";
    setTimeout(pollHealth, 3000);
  } else {
    text.textContent = "Engine Failed";
    strip.textContent = "LUT Engine Offline";
    pill.classList.add("bg-red-50", "border-red-200", "text-red-700");
    core.className = "relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500";
    ping.className = "hidden";
    wave.classList.add("hidden");
    bDot.className = "relative inline-flex rounded-full h-2 w-2 bg-red-500";
    bPing.className = "hidden";
    bText.textContent = "Spectre LUT Backend Offline";
  }
}

function pollHealth() {
  fetch("/api/v1/health").then(r => r.json()).then(applyHealth)
    .catch(() => {
      $("engine-text").textContent = "Server Unreachable";
      $("backend-dot").className = "relative inline-flex rounded-full h-2 w-2 bg-red-500";
      $("backend-text").textContent = "Spectre LUT Backend Offline";
    });
}

/* -------------------------------------------------------------- banner -- */
function setBanner(kind, icon, title, sub, pillHtml, badgeHtml) {
  const el = $("status-banner");
  const base = "rounded-xl p-4 shadow-2xs flex flex-col sm:flex-row sm:items-center justify-between gap-3 ";
  const styles = {
    idle:  { box: "bg-slate-50 border border-slate-200", title: "text-slate-900", sub: "text-slate-500" },
    ok:    { box: "bg-gradient-to-r from-emerald-50 via-emerald-50/60 to-cyan-50/40 border border-emerald-200",
             title: "text-emerald-950", sub: "text-emerald-700" },
    warn:  { box: "bg-amber-50 border border-amber-300", title: "text-amber-950", sub: "text-amber-700" },
    error: { box: "bg-red-50 border border-red-300", title: "text-red-950", sub: "text-red-700" },
  }[kind];
  el.className = base + styles.box;
  el.innerHTML =
    '<div class="flex items-center gap-3.5">' +
    '<div class="w-9 h-9 rounded-full flex items-center justify-center text-white font-bold flex-shrink-0 shadow-sm ' + icon[0] + '">' + icon[1] + "</div>" +
    '<div><div class="flex items-center gap-2">' +
    '<h3 class="text-sm font-bold ' + styles.title + '">' + title + "</h3>" +
    (pillHtml || "") + "</div>" +
    '<p class="text-xs font-mono mt-0.5 ' + styles.sub + '">' + sub + "</p></div></div>" +
    (badgeHtml ? '<div class="flex items-center gap-2">' + badgeHtml + "</div>" : "");
  el.classList.remove("hidden");
}

const ICONS = {
  idle:  ["bg-slate-400 ring-2 ring-slate-100", "i"],
  ok:    ["bg-gradient-to-tr from-emerald-600 to-emerald-400 ring-2 ring-emerald-100",
          '<svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2.5" viewbox="0 0 24 24"><path d="M4.5 12.75l6 6 9-13.5" stroke-linecap="round" stroke-linejoin="round"></path></svg>'],
  warn:  ["bg-amber-500 ring-2 ring-amber-100", "!"],
  error: ["bg-red-500 ring-2 ring-red-100", "✕"],
};

/* ------------------------------------------------------------- render -- */
function hideResults() {
  $("results-area").classList.add("hidden");
  $("export-btn").disabled = true;
  current = null;
}

function renderSuccess(b) {
  const p = b.presentation, m = p.metrics, path = b.sizing_path;
  current = b;
  $("export-btn").disabled = false;

  const pill = '<span class="flex items-center gap-1 text-[11px] font-mono ' +
    'text-emerald-700 bg-white/80 px-2 py-0.5 rounded-full border border-emerald-200">' +
    '<svg class="w-3 h-3 text-emerald-600" fill="none" stroke="currentColor" ' +
    'stroke-width="2.5" viewbox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12">' +
    '</polyline></svg>LUT-Verified</span>';
  const badge = '<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg ' +
    'text-xs font-mono font-bold bg-emerald-100 text-emerald-900 border border-emerald-300 shadow-2xs">' +
    '<span class="w-2 h-2 rounded-full bg-emerald-500 chip-glow-pulse"></span>VERIFIED CANDIDATE</span>';
  setBanner("ok", ICONS.ok, "Verified sizing candidate found",
    esc(path.pipeline_status) + " · " + path.n_oracle_evals + " evaluations converged",
    pill, badge);

  $("m-gain").textContent = fmt(m.gain_dB, 2);
  $("m-gain-sub").textContent = "● Target: ≥ " + fmt(b.user_specs.Gain_min, 2);
  $("m-gbw").textContent = fmt(m.gbw_MHz, 2);
  const gbwMarginPct = (m.gbw_MHz - b.user_specs.GBW_min / 1e6)
    / (b.user_specs.GBW_min / 1e6) * 100;
  $("m-gbw-sub").textContent = signed(gbwMarginPct, 1, "%") + " over target";
  $("m-pm").textContent = fmt(m.pm_deg, 2);
  $("m-pm-sub").textContent = m.pm_deg >= PM_FLOOR
    ? "Stable (> " + PM_FLOOR + "°)" : "Below floor";
  $("m-pwr").textContent = fmt(m.power_uW, 2);
  const pwrPct = (b.user_specs.Power_max / 1e6 - m.power_uW)
    / (b.user_specs.Power_max / 1e6) * 100;
  $("m-pwr-sub").textContent = signed(pwrPct, 1, "%") + " budget";

  const g1 = p.m1_m2, g3 = p.m3_m4;
  $("geometry-body").innerHTML =
    row2("bg-cyan-500 ring-cyan-100", "hover:bg-cyan-50/30", "M1 = M2",
      "Input Pair, NMOS", "M5 12h14M13 6l6 6-6 6", g1.w_um, g1.l_um, "group-hover:text-cyan-700") +
    row2("bg-indigo-500 ring-indigo-100", "hover:bg-indigo-50/30", "M3 = M4",
      "Mirror Load, PMOS", "", g3.w_um, g3.l_um, "group-hover:text-indigo-700") +
    '<tr class="hover:bg-amber-50/30 transition-colors bg-slate-50/30 font-sans group">' +
    '<td class="py-2.5 px-5 font-mono"><div class="flex items-center gap-2">' +
    '<span class="w-2.5 h-2.5 rounded-full bg-amber-500 ring-2 ring-amber-100 group-hover:scale-125 transition-transform"></span>' +
    '<span class="font-bold text-slate-900">I<sub>tail</sub></span>' +
    '<span class="text-xs text-slate-500">(Bias Sink Current)</span></div></td>' +
    '<td class="py-2.5 px-5 text-right font-mono font-bold text-slate-900 tabular-numbers" colspan="2">' +
    fmt(p.itail_uA, 3) + ' <span class="font-normal text-slate-500">µA</span></td>' +
    '<td class="py-2.5 px-5 text-right font-mono text-xs text-slate-500" colspan="2">' +
    "V<sub>tail</sub> ≈ " + fmt(m.vtail_V, 3) + " V</td></tr>";

  const visible = (b.constraints || []).filter(c => !C_HIDE.has(c.name));
  $("constraint-body").innerHTML = visible.map(constraintRow).join("");
  const nPass = visible.filter(c => c.passed).length;
  const nAll = visible.length;
  $("checks-text").textContent = nPass + " / " + nAll + " Checks Passed";
  const checksBadge = $("checks-badge");
  checksBadge.classList.remove("text-emerald-700", "bg-emerald-50", "border-emerald-200",
    "text-red-700", "bg-red-50", "border-red-200");
  if (nPass === nAll) checksBadge.classList.add("text-emerald-700", "bg-emerald-50", "border-emerald-200");
  else checksBadge.classList.add("text-red-700", "bg-red-50", "border-red-200");

  $("it-value").textContent = "GBW = " + fmt(b.internal_specs.GBW_min / 1e6, 3) + " MHz";
  $("pa-value").textContent = path.pipeline_status;
  $("results-area").classList.remove("hidden");
}

function row2(dotCls, hoverCls, name, role, roleIcon, w, l, wHover) {
  const roleHtml = roleIcon
    ? ' <svg class="w-3 h-3 text-cyan-600 opacity-60 group-hover:opacity-100" fill="none" stroke="currentColor" stroke-width="2" viewbox="0 0 24 24"><path d="' + roleIcon + '"></path></svg>'
    : ' <svg class="w-3 h-3 text-indigo-600 opacity-60 group-hover:opacity-100" fill="none" stroke="currentColor" stroke-width="2" viewbox="0 0 24 24"><circle cx="12" cy="12" r="3"></circle></svg>';
  return '<tr class="transition-colors group cursor-default ' + hoverCls + '">' +
    '<td class="py-3 px-5"><div class="flex items-center gap-2">' +
    '<span class="w-2.5 h-2.5 rounded-full ' + dotCls + ' group-hover:scale-125 transition-transform"></span>' +
    '<span class="font-bold text-slate-900">' + name + "</span>" +
    '<span class="text-xs text-slate-500 font-sans flex items-center gap-1">(' + role + ")" + roleHtml + "</span></div></td>" +
    '<td class="py-3 px-5 text-right font-bold text-slate-900 tabular-numbers transition-colors ' + wHover + '">' + fmt(w, 3) + "</td>" +
    '<td class="py-3 px-5 text-right text-slate-700 tabular-numbers">' + fmt(l, 3) + "</td>" +
    '<td class="py-3 px-5 text-right text-slate-500 tabular-numbers">' + fmt(w / l, 2) + "</td>" +
    '<td class="py-3 px-5 text-right text-slate-600 tabular-numbers font-semibold">1×</td></tr>';
}

/* display scale = multiplier into the shown unit (SI value * scale) */
const C_LABELS = {
  Gain_min: ["dB", 1], GBW_min: ["MHz", 1e-6], Power_max: ["µW", 1e6],
  PM_min: ["°", 1], Sat_margin_min: ["V", 1],
};
const C_HIDE = new Set(["W_nmos_max", "W_pmos_max"]);  // internal bounds

function constraintRow(c) {
  const chip = c.passed
    ? '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500 text-white tracking-wider shadow-2xs">PASS</span>'
    : '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-red-500 text-white tracking-wider shadow-2xs">FAIL</span>';
  let req = "—", ach = "—", margin = "—";
  if (c.name === "L_domain") {
    req = fmt(c.limit[0] * 1e6, 2) + " – " + fmt(c.limit[1] * 1e6, 2) + " µm";
    ach = (c.achieved && c.achieved.length)
      ? fmt(Math.min(...c.achieved) * 1e6, 2) + " – " + fmt(Math.max(...c.achieved) * 1e6, 2) + " µm"
      : "—";
  } else {
    const u = C_LABELS[c.name] || ["", 1];
    req = c.limit === null || c.limit === undefined ? "—" : fmt(c.limit * u[1], 2) + " " + u[0];
    ach = c.achieved === null || c.achieved === undefined ? "—" : fmt(c.achieved * u[1], 2) + " " + u[0];
    margin = signed(c.margin === null || c.margin === undefined ? null : c.margin * u[1], 2, u[0]);
  }
  const achCls = c.passed ? "font-semibold text-slate-900" : "font-semibold text-red-700";
  return '<tr class="hover:bg-slate-50 transition-colors">' +
    '<td class="py-2.5 px-5 font-semibold text-slate-800">' + esc(c.name) + "</td>" +
    '<td class="py-2.5 px-5 text-right text-slate-600 tabular-numbers">' + req + "</td>" +
    '<td class="py-2.5 px-5 text-right tabular-numbers ' + achCls + '">' + ach + "</td>" +
    '<td class="py-2.5 px-5 text-right text-slate-500 tabular-numbers">' + margin + "</td>" +
    '<td class="py-2.5 px-5 text-center">' + chip + "</td></tr>";
}

function renderUnresolved(b) {
  hideResults();
  const badge = '<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg ' +
    'text-xs font-mono font-bold bg-amber-100 text-amber-900 border border-amber-300 shadow-2xs">' +
    '<span class="w-2 h-2 rounded-full bg-amber-500"></span>UNRESOLVED</span>';
  setBanner("warn", ICONS.warn, "No verified sizing within budget",
    b.n_oracle_evals + " evaluations · not proof of infeasibility — try relaxing a spec",
    null, badge);
  $("it-value").textContent = "—";
  $("pa-value").textContent = "unresolved";
}

function renderError(code, message) {
  hideResults();
  const hint = code === "not_ready" ? "engine loading — wait for the green status"
    : code === "validation_error" ? "check the allowed ranges under each field"
    : code === "sizing_failed" ? "nothing was sized; see server log" : "";
  setBanner("error", ICONS.error, "Request refused",
    esc(message || "unknown error") + (hint ? " — " + hint : ""), null, null);
  $("it-value").textContent = "—";
  $("pa-value").textContent = "—";
}

function renderIdle() {
  hideResults();
  setBanner("idle", ICONS.idle, "Synthesis engine idle",
    "Configure the target specifications and run the engine", null, null);
  $("it-value").textContent = "—";
  $("pa-value").textContent = "—";
}

/* ------------------------------------------------------------- export -- */
$("export-btn").addEventListener("click", () => {
  if (!current) return;
  const body = {
    W1: current.design.m1_m2.w_m, L1: current.design.m1_m2.l_m,
    W3: current.design.m3_m4.w_m, L3: current.design.m3_m4.l_m,
    Itail: current.design.itail_a, CL_pF: current.user_specs.CL_pF,
  };
  $("export-btn").disabled = true;
  fetch("/api/v1/netlist", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(r => {
    if (!r.ok) throw new Error("netlist export failed (" + r.status + ")");
    return r.text();
  }).then(text => {
    const blob = new Blob([text], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ota_sizing_" + fmt(current.user_specs.GBW_min / 1e6, 0) + "MHz.scs";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }).catch(err => {
    setBanner("error", ICONS.error, "Export failed", esc(err.message), null, null);
  }).finally(() => {
    if (current) $("export-btn").disabled = false;
  });
});

/* -------------------------------------------------------------- form -- */
function updateOvershoot() {
  const v = parseFloat($("min-gbw").value);
  $("overshoot-hint").textContent = Number.isFinite(v)
    ? "Overshoot target: " + fmt(v * GUARD, 3) + " MHz (" + GUARD + "×)"
    : "Overshoot target: — (" + GUARD + "×)";
}
$("min-gbw").addEventListener("input", updateOvershoot);

$("reset-btn").addEventListener("click", () => {
  Object.entries(DEFAULTS).forEach(([id, v]) => { $(id).value = v; });
  updateOvershoot();
  renderIdle();
});

function startProgress() {
  const t0 = Date.now();
  $("submit-btn").disabled = true;
  const tick = () => {
    $("submit-label").textContent = "Synthesizing… " + Math.round((Date.now() - t0) / 1000) + " s";
  };
  tick();
  pollTimer = setInterval(tick, 500);
}

function stopProgress() {
  clearInterval(pollTimer);
  $("submit-btn").disabled = false;
  $("submit-label").textContent = "Size & Synthesize OTA";
}

$("size-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = {
    Gain_min_dB: parseFloat($("min-gain").value),
    GBW_min_MHz: parseFloat($("min-gbw").value),
    CL_pF: parseFloat($("load-cap").value),
    Power_max_uW: parseFloat($("max-power").value),
  };
  for (const [k, v] of Object.entries(payload)) {
    if (!Number.isFinite(v)) {
      renderError("validation_error", "Field " + k + " is not a finite number");
      return;
    }
  }
  startProgress();
  try {
    const r = await fetch("/api/v1/size", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await r.json().catch(() => null);
    stopProgress();
    if (r.status === 200 && body && body.status === "success") renderSuccess(body);
    else if (r.status === 200 && body && body.status === "unresolved") renderUnresolved(body);
    else if (body && body.error) renderError(body.error.code, body.error.message);
    else renderError(null, "Unexpected response (" + r.status + ")");
  } catch (err) {
    stopProgress();
    renderError(null, "Server unreachable");
  }
});

updateOvershoot();
renderIdle();
pollHealth();
