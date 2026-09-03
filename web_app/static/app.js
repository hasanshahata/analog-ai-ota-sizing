/* OTA sizing UI - the server validates, guards, and verifies; this file
 * only collects and renders. Unresolved/error states show no geometry. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const resultEl = $("#result");
const form = $("#size-form");
const submitBtn = $("#submit");
const progressEl = $("#progress");
const progressText = $("#progress-text");

let pollTimer = null;

const SCOPE = "Nominal LUT candidate — not PVT / post-layout signoff. " +
  "Cadence is the final authority.";

function fmt(v, d) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("en-US",
    { minimumFractionDigits: d, maximumFractionDigits: d });
}

function kv(k, v) {
  return '<div><span class="k">' + k + '</span><span class="v">' + v + "</span></div>";
}

function esc(s) {
  return String(s).replace(/[&<>"']/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* ------------------------------------------------------------ engine -- */
function checkEngine() {
  fetch("/api/v1/health").then(r => r.json()).then(h => {
    const dot = $("#engine-dot"), text = $("#engine-text");
    dot.className = "dot dot-" + h.state;
    text.textContent = h.state === "ready" ? "ready"
      : h.state === "loading" ? "loading LUTs…" : "failed — see server log";
    if (h.state === "loading") setTimeout(checkEngine, 3000);
  }).catch(() => {
    $("#engine-dot").className = "dot dot-failed";
    $("#engine-text").textContent = "server unreachable";
  });
}

/* ----------------------------------------------------------- progress -- */
function startProgress() {
  const t0 = Date.now();
  progressEl.hidden = false;
  submitBtn.disabled = true;
  const tick = () => { progressText.textContent = Math.round((Date.now() - t0) / 1000) + " s"; };
  tick();
  pollTimer = setInterval(tick, 500);
}

function stopProgress() {
  clearInterval(pollTimer);
  progressEl.hidden = true;
  submitBtn.disabled = false;
}

/* ----------------------------------------------------------- renderers -- */
function renderSuccess(b) {
  const p = b.presentation, m = p.metrics, path = b.sizing_path;
  const html = [];

  html.push('<div class="banner ok">✔ Verified sizing' +
    '<div class="meta">' + esc(path.pipeline_status) + " · " +
    path.n_oracle_evals + " evals</div></div>");

  html.push('<div class="card"><table>' +
    "<tr><th></th><th class='num'>W (µm)</th><th class='num'>L (µm)</th></tr>" +
    "<tr><td>M1 = M2</td><td class='num'>" + fmt(p.m1_m2.w_um, 3) +
    "</td><td class='num'>" + fmt(p.m1_m2.l_um, 3) + "</td></tr>" +
    "<tr><td>M3 = M4</td><td class='num'>" + fmt(p.m3_m4.w_um, 3) +
    "</td><td class='num'>" + fmt(p.m3_m4.l_um, 3) + "</td></tr>" +
    "<tr><td>I<sub>tail</sub></td><td class='num'>" + fmt(p.itail_uA, 3) +
    " µA</td><td class='num'></td></tr></table>");

  html.push('<div class="kv" style="margin-top:12px">');
  html.push(kv("Gain", fmt(m.gain_dB, 2) + " dB"));
  html.push(kv("GBW", fmt(m.gbw_MHz, 3) + " MHz"));
  html.push(kv("Phase margin", fmt(m.pm_deg, 2) + "°"));
  html.push(kv("Power", fmt(m.power_uW, 3) + " µW"));
  html.push("</div></div>");

  html.push('<div class="card"><table>' +
    "<tr><th>Constraint</th><th class='num'>Required</th>" +
    "<th class='num'>Achieved</th><th></th></tr>");
  const units = { Gain_min: ["dB", 1], GBW_min: ["MHz", 1e6],
                  Power_max: ["µW", 1e6], PM_min: ["°", 1] };
  (b.constraints || []).forEach(c => {
    const u = units[c.name] || ["", 1];
    html.push("<tr><td>" + esc(c.name) + "</td>" +
      "<td class='num'>" + (c.limit === null ? "—" : fmt(c.limit / u[1], 2) + " " + u[0]) + "</td>" +
      "<td class='num'>" + (c.achieved === null ? "—" : fmt(c.achieved / u[1], 2) + " " + u[0]) + "</td>" +
      "<td><span class='chip " + (c.passed ? "pass'>PASS" : "fail'>FAIL") + "</span></td></tr>");
  });
  html.push("</table>");
  html.push('<div class="guardline">GBW target ' +
    fmt(b.internal_specs.GBW_min / 1e6, 3) + " MHz = user " +
    fmt(b.user_specs.GBW_min / 1e6, 3) + " × " +
    fmt(b.calibration.gbw_guard_band + 1, 2) +
    " · policy " + esc(b.calibration.version) + "</div></div>");

  html.push('<div class="scope">' + SCOPE + "</div>");
  return html.join("");
}

function renderUnresolved(b) {
  return '<div class="banner warn">⚠ Unresolved within budget' +
    '<div class="meta">' + (b.n_oracle_evals || 0) + " evals · no design found — " +
    "not proof of infeasibility. Try relaxing a spec.</div></div>" +
    '<div class="scope">' + SCOPE + "</div>";
}

function renderError(code, message) {
  const hint = code === "not_ready" ? " — engine loading, wait for the green dot"
    : code === "validation_error" ? " — check the allowed ranges (min/max on each field)"
    : code === "sizing_failed" ? " — nothing was sized, see server log" : "";
  return '<div class="banner bad">✖ ' + esc(message || "request failed") +
    esc(hint) + "</div>";
}

/* -------------------------------------------------------------- submit -- */
form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  resultEl.innerHTML = "";
  const payload = {
    Gain_min_dB: parseFloat($("#gain").value),
    GBW_min_MHz: parseFloat($("#gbw").value),
    CL_pF: parseFloat($("#cl").value),
    Power_max_uW: parseFloat($("#power").value),
  };
  for (const [k, v] of Object.entries(payload)) {
    if (!Number.isFinite(v)) {
      resultEl.innerHTML = renderError("validation_error", k + " is not a number");
      return;
    }
  }
  startProgress();
  try {
    const r = await fetch("/api/v1/size", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await r.json().catch(() => null);
    stopProgress();
    if (r.status === 200 && body && body.status === "success") {
      resultEl.innerHTML = renderSuccess(body);
    } else if (r.status === 200 && body && body.status === "unresolved") {
      resultEl.innerHTML = renderUnresolved(body);
    } else if (body && body.error) {
      resultEl.innerHTML = renderError(body.error.code, body.error.message);
    } else {
      resultEl.innerHTML = renderError(null, "unexpected response (" + r.status + ")");
    }
  } catch (err) {
    stopProgress();
    resultEl.innerHTML = renderError(null, "server unreachable");
  }
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

checkEngine();
