/* OTA Sizing Explorer - wiring for the stitch_UI v3 design.
 * The server validates, guards (25% internal GBW), and verifies; this file
 * renders real data only. Unresolved/error states show no geometry. */
"use strict";

const $ = (id) => document.getElementById(id);

const DEFAULTS = { "min-gain": 35, "min-gbw": 100, "load-cap": 1, "max-power": 200 };
const PM_FLOOR = 45;            // verifier default (deg)

let current = null;             // last verified API response (enables export)
let pollTimer = null;

/* ------------------------------------------------------------ helpers -- */
function fmt(v, d) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  return Number(v).toLocaleString("en-US",
    { minimumFractionDigits: d, maximumFractionDigits: d });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

const CHECK_ICON = '<svg class="w-3 h-3" fill="none" stroke="currentColor" ' +
  'viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" stroke-linecap="round" ' +
  'stroke-linejoin="round" stroke-width="2.5"></path></svg>';

/* -------------------------------------------------------------- health -- */
function applyHealth(h) {
  const dot = $("engine-dot-core"), text = $("engine-text");
  if (h.state === "ready") {
    text.textContent = "Engine Ready";
    dot.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 pulse-beacon";
  } else if (h.state === "loading") {
    text.textContent = "Engine Loading";
    dot.className = "w-2.5 h-2.5 rounded-full bg-amber-400 pulse-beacon";
    setTimeout(pollHealth, 3000);
  } else {
    text.textContent = "Engine Failed";
    dot.className = "w-2.5 h-2.5 rounded-full bg-red-500";
  }
}

function pollHealth() {
  fetch("/api/v1/health").then(r => r.json()).then(applyHealth)
    .catch(() => {
      $("engine-text").textContent = "Server Unreachable";
      $("engine-dot-core").className = "w-2.5 h-2.5 rounded-full bg-red-500";
    });
}

/* ------------------------------------------------------------- render -- */
function hideResults() {
  $("results-area").classList.add("hidden");
  $("status-banner").classList.add("hidden");
  $("export-btn").disabled = true;
  current = null;
}

function kpiChip(text) {
  return CHECK_ICON + "<span>" + esc(text) + "</span>";
}

function satMarginMV(b) {
  const c = (b.constraints || []).find(c => c.name === "Sat_margin_min");
  return c && c.achieved !== null && c.achieved !== undefined
    ? c.achieved * 1000 : null;
}

function renderSuccess(b) {
  const p = b.presentation, m = p.metrics;
  current = b;
  $("export-btn").disabled = false;
  $("status-banner").classList.add("hidden");

  $("m-gain").textContent = fmt(m.gain_dB, 2);
  $("m-gain-sub").innerHTML = kpiChip("≥ " + fmt(b.user_specs.Gain_min, 2) + " Target");
  $("m-gbw").textContent = fmt(m.gbw_MHz, 2);
  const gbwMarginPct = (m.gbw_MHz - b.user_specs.GBW_min / 1e6)
    / (b.user_specs.GBW_min / 1e6) * 100;
  $("m-gbw-sub").innerHTML = kpiChip("+" + fmt(gbwMarginPct, 1) + "% Margin");
  $("m-pm").textContent = fmt(m.pm_deg, 2);
  $("m-pm-sub").innerHTML = kpiChip("Stable (> " + PM_FLOOR + "°)");
  $("m-pwr").textContent = fmt(m.power_uW, 2);
  const pMaxUW = b.user_specs.Power_max * 1e6;   // W -> µW
  const pwrPct = (pMaxUW - m.power_uW) / pMaxUW * 100;
  $("m-pwr-sub").innerHTML = kpiChip("−" + fmt(pwrPct, 1) + "% Budget");

  const g1 = p.m1_m2, g3 = p.m3_m4;
  const sat = satMarginMV(b);
  const satCell = (label) =>
    '<div class="font-semibold text-slate-900">Sat. margin ≈ ' +
    fmt(sat, 0) + " mV</div>" +
    '<div class="text-[11px] text-emerald-600 font-bold flex items-center justify-end gap-1 mt-0.5">' +
    CHECK_ICON + label + "</div>";

  $("geometry-body").innerHTML =
    '<tr class="cold-table-row">' +
    '<td class="py-4 px-6"><div class="font-bold text-slate-900 text-sm flex items-center gap-2">' +
    '<span>M1 = M2</span>' +
    '<span class="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-sky-100 text-sky-800 font-bold border border-sky-200">NMOS</span></div>' +
    '<div class="text-slate-500 text-xs mt-0.5 font-sans">Differential Input Pair</div></td>' +
    '<td class="py-4 px-6 text-right font-bold text-slate-900 text-sm tabular-numbers">' + fmt(g1.w_um, 3) + "</td>" +
    '<td class="py-4 px-6 text-right font-semibold text-slate-700 text-sm tabular-numbers">' + fmt(g1.l_um, 3) + "</td>" +
    '<td class="py-4 px-6 text-right">' + satCell("Saturation Checked") + "</td></tr>" +
    '<tr class="cold-table-row">' +
    '<td class="py-4 px-6"><div class="font-bold text-slate-900 text-sm flex items-center gap-2">' +
    '<span>M3 = M4</span>' +
    '<span class="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 font-bold border border-indigo-200">PMOS</span></div>' +
    '<div class="text-slate-500 text-xs mt-0.5 font-sans">Active Current Mirror Load</div></td>' +
    '<td class="py-4 px-6 text-right font-bold text-slate-900 text-sm tabular-numbers">' + fmt(g3.w_um, 3) + "</td>" +
    '<td class="py-4 px-6 text-right font-semibold text-slate-700 text-sm tabular-numbers">' + fmt(g3.l_um, 3) + "</td>" +
    '<td class="py-4 px-6 text-right">' + satCell("Saturation Checked") + "</td></tr>" +
    '<tr class="cold-table-row bg-sky-50/40">' +
    '<td class="py-4 px-6"><div class="font-bold text-slate-900 text-sm flex items-center gap-2">' +
    "<span>I<sub>tail</sub></span>" +
    '<span class="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-bold border border-emerald-200">Bias</span></div>' +
    '<div class="text-slate-500 text-xs mt-0.5 font-sans">Ideal Tail Current Sink</div></td>' +
    '<td class="py-4 px-6 text-center"><div class="inline-flex items-center gap-2 bg-white px-3 py-1 rounded-lg border border-sky-200">' +
    '<span class="text-slate-500 text-[11px]">Total Tail Current:</span>' +
    '<span class="font-bold text-sky-700 text-sm tabular-numbers">' + fmt(p.itail_uA, 3) + " µA</span></div></td>" +
    '<td class="py-4 px-6 text-center"><div class="inline-flex items-center gap-2 bg-white px-3 py-1 rounded-lg border border-sky-200">' +
    '<span class="text-slate-500 text-[11px]">Branch Bias:</span>' +
    '<span class="font-bold text-slate-800 text-sm tabular-numbers">' + fmt(p.itail_uA / 2, 3) + " µA</span></div></td>" +
    '<td class="py-4 px-6 text-right">' + satCell("Saturation Checked") + "</td></tr>";

  $("results-area").classList.remove("hidden");
}

function showStatus(kind, title, sub, chipText) {
  const styles = {
    warn:  ["border-amber-200", "bg-amber-500", "text-amber-900",
            "text-amber-700", "bg-amber-50 text-amber-800 border-amber-200"],
    error: ["border-red-200", "bg-red-500", "text-red-900",
            "text-red-600", "bg-red-50 text-red-700 border-red-200"],
  }[kind];
  $("status-banner").className = "bg-white rounded-2xl border p-4 shadow-sm " +
    "flex flex-col sm:flex-row sm:items-center justify-between gap-3 " + styles[0];
  $("status-banner").innerHTML =
    '<div class="flex items-center gap-3">' +
    '<span class="w-2.5 h-2.5 rounded-full ' + styles[1] + ' flex-shrink-0"></span>' +
    '<div><p class="text-sm font-bold ' + styles[2] + '">' + title + "</p>" +
    '<p class="text-xs font-mono mt-0.5 ' + styles[3] + '">' + sub + "</p></div></div>" +
    '<span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-mono font-bold border ' +
    styles[4] + '">' + chipText + "</span>";
  $("status-banner").classList.remove("hidden");
}

function renderUnresolved(b) {
  hideResults();
  showStatus("warn", "No verified sizing within budget",
    b.n_oracle_evals + " evaluations · not proof of infeasibility — try relaxing a spec",
    "UNRESOLVED");
}

function renderError(code, message) {
  hideResults();
  const hint = code === "not_ready" ? "engine loading — wait for Engine Ready"
    : code === "validation_error" ? "values must be inside the allowed ranges"
    : code === "sizing_failed" ? "nothing was sized; see server log" : "";
  showStatus("error", "Request refused",
    esc(message || "unknown error") + (hint ? " — " + hint : ""), "ERROR");
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
    renderError(null, err.message);
  }).finally(() => {
    if (current) $("export-btn").disabled = false;
  });
});

/* -------------------------------------------------------------- form -- */
$("reset-btn").addEventListener("click", () => {
  Object.entries(DEFAULTS).forEach(([id, v]) => { $(id).value = v; });
  hideResults();
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

pollHealth();
