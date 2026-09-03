/* Ideal-tail 5T OTA sizing UI (Phase W3).
 * The server is the only authority: it validates, guards (25% internal GBW),
 * verifies, and decides success. This file only collects, renders, and
 * never fabricates dimensions - unresolved/error states render no geometry.
 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const resultEl = $("#result");
const form = $("#size-form");
const submitBtn = $("#submit");
const progressEl = $("#progress");
const progressText = $("#progress-text");

const DEFAULTS = { gain: 35, gbw: 100, cl: 1, power: 200 };

let pollTimer = null;
let t0 = 0;

/* ------------------------------------------------------------ helpers -- */
function fmt(v, digits) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function checkEngine() {
  fetch("/api/v1/health").then(r => r.json()).then(h => {
    const dot = $("#engine-dot"), text = $("#engine-text");
    dot.className = "dot dot-" + h.state;
    if (h.state === "ready") {
      text.textContent = "sizing engine ready — policy " + h.policy_version;
    } else if (h.state === "loading") {
      text.textContent = "sizing engine loading (LUTs, one-time)…";
      setTimeout(checkEngine, 3000);
    } else {
      text.textContent = "sizing engine failed: " + (h.detail || "see server logs");
    }
  }).catch(() => {
    $("#engine-dot").className = "dot dot-failed";
    $("#engine-text").textContent = "server unreachable";
  });
}

function startProgress() {
  t0 = Date.now();
  progressEl.hidden = false;
  submitBtn.disabled = true;
  form.setAttribute("aria-busy", "true");
  resultEl.setAttribute("aria-busy", "true");
  const tick = () => {
    progressText.textContent =
      "working… " + Math.round((Date.now() - t0) / 1000) + " s";
  };
  tick();
  pollTimer = setInterval(tick, 500);
}

function stopProgress() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  progressEl.hidden = true;
  submitBtn.disabled = false;
  form.setAttribute("aria-busy", "false");
  resultEl.setAttribute("aria-busy", "false");
}

function banner(kind, title, bodyHtml) {
  return '<div class="banner ' + kind + '">' + title +
         (bodyHtml ? "<p>" + bodyHtml + "</p>" : "") + "</div>";
}

function scopeBox(text) {
  return '<div class="scope"><strong>Scope warning.</strong> ' + text + "</div>";
}

/* ------------------------------------------------------------ renderers -- */
function renderSuccess(b) {
  const p = b.presentation || {};
  const m = p.metrics || {};
  const html = [];
  html.push(banner("ok", "✔ Verified sizing candidate",
    "Every hard constraint passes against the nominal LUT model " +
    "(path: <code>" + (b.sizing_path.pipeline_status || "verified") + "</code>, " +
    b.sizing_path.n_oracle_evals + " oracle evaluations)."));

  html.push('<div class="card">');
  html.push('<div class="section-title">Device sizing (display rounding; ' +
            'verdicts use full precision)</div><table>');
  html.push("<tr><th>Device</th><th class='num'>W (µm)</th>" +
            "<th class='num'>L (nm)</th></tr>");
  html.push("<tr><td>M1 = M2 <span class='match'>(matched input pair)</span></td>" +
            "<td class='num'>" + fmt(p.m1_m2 && p.m1_m2.w_um, 3) + "</td>" +
            "<td class='num'>" + fmt(p.m1_m2 && p.m1_m2.l_nm, 1) + "</td></tr>");
  html.push("<tr><td>M3 = M4 <span class='match'>(matched mirror load)</span></td>" +
            "<td class='num'>" + fmt(p.m3_m4 && p.m3_m4.w_um, 3) + "</td>" +
            "<td class='num'>" + fmt(p.m3_m4 && p.m3_m4.l_nm, 1) + "</td></tr>");
  html.push("<tr><td>Ideal tail current</td><td class='num'>" +
            fmt(p.itail_uA, 3) + " µA</td><td class='num'>—</td></tr>");
  html.push("</table>");

  html.push('<div class="section-title">Predicted nominal LUT metrics</div>' +
            '<div class="kv">');
  html.push(kv("DC gain", fmt(m.gain_dB, 2) + " dB"));
  html.push(kv("GBW", fmt(m.gbw_MHz, 3) + " MHz"));
  html.push(kv("Phase margin", fmt(m.pm_deg, 2) + "°"));
  html.push(kv("Power", fmt(m.power_uW, 3) + " µW"));
  html.push(kv("Output DC", fmt(m.vout_V, 4) + " V"));
  html.push(kv("Tail node", fmt(m.vtail_V, 4) + " V"));
  html.push(kv("Mirror node", fmt(m.vmirror_V, 4) + " V"));
  html.push("</div></div>");

  html.push('<div class="card">');
  html.push('<div class="section-title">Hard-constraint margins (user contract)</div>');
  html.push("<table><tr><th>Constraint</th><th class='num'>Required</th>" +
            "<th class='num'>Achieved</th><th class='num'>Margin</th>" +
            "<th>Verdict</th></tr>");
  (b.constraints || []).forEach(c => {
    const unit = c.name === "GBW_min" ? " MHz" : c.name === "Power_max" ? " µW"
               : c.name === "Gain_min" ? " dB" : c.name === "PM_min" ? "°"
               : c.name === "CL_pF" ? " pF" : "";
    const scale = c.name === "GBW_min" ? 1e6 : c.name === "Power_max" ? 1e6 : 1;
    html.push("<tr><td>" + esc(c.name) + "</td>" +
              "<td class='num'>" + fmt(c.limit !== null ? c.limit / scale : null, 3) + unit + "</td>" +
              "<td class='num'>" + fmt(c.achieved !== null ? c.achieved / scale : null, 3) + unit + "</td>" +
              "<td class='num'>" + fmt(c.margin !== null ? c.margin / scale : null, 3) + unit + "</td>" +
              "<td><span class='chip " + (c.passed ? "pass'>PASS" : "fail'>FAIL") + "</span></td></tr>");
  });
  html.push("</table>");

  html.push('<div class="section-title">Deployment guard provenance</div><div class="kv">');
  html.push(kv("Requested GBW (user)", fmt(b.user_specs.GBW_min / 1e6, 3) + " MHz"));
  html.push(kv("Internal guarded GBW target",
              fmt(b.internal_specs.GBW_min / 1e6, 3) + " MHz"));
  html.push(kv("Guard band ×",
              fmt((b.calibration && b.calibration.gbw_guard_band) || null, 2)));
  html.push(kv("Policy version",
              (b.calibration && b.calibration.version) || "—"));
  html.push(kv("Internal contract verdict",
              b.verdict.internal_verdict ? "PASS" : "FAIL"));
  html.push("</div></div>");

  html.push(scopeBox(b.scope_warning || ""));
  return html.join("");
}

function kv(k, v) {
  return '<div><span class="k">' + k + '</span><span class="v">' + v + "</span></div>";
}

function renderUnresolved(b) {
  return banner("warn", "⚠ No verified design within budget",
      esc(b.explanation || "") + "<br><br><strong>Suggestion.</strong> " +
      esc(b.guidance || "") + "<br><br>No transistor dimensions are returned. " +
      "(" + (b.n_oracle_evals || 0) + " oracle evaluations spent.)") +
    scopeBox(b.scope_warning || "");
}

function renderError(code, message) {
  let advice = "";
  if (code === "not_ready") advice = " The engine is still loading or failed — wait for the status line to show ready, then retry.";
  if (code === "validation_error") advice = " Check the highlighted allowed ranges above.";
  if (code === "sizing_failed") advice = " Nothing was sized; no partial design is shown. See the server log for details.";
  return banner("bad", "✖ Request refused" + (code ? " (" + code + ")" : ""),
      esc(message || "unknown error") + advice) +
    scopeBox("No sizing was produced for this request.");
}

function renderNetworkError() {
  return banner("bad", "✖ Server unreachable",
      "The sizing service did not respond. Confirm it is running " +
      "(see the user guide launch command) and retry. " +
      "No sizing was produced for this request.");
}

function esc(s) {
  return String(s).replace(/[&<>"']/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* -------------------------------------------------------------- submit -- */
form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  resultEl.hidden = false;
  resultEl.innerHTML = "";                       // never show stale results
  const payload = {
    Gain_min_dB: parseFloat($("#gain").value),
    GBW_min_MHz: parseFloat($("#gbw").value),
    CL_pF: parseFloat($("#cl").value),
    Power_max_uW: parseFloat($("#power").value),
  };
  for (const [k, v] of Object.entries(payload)) {
    if (!Number.isFinite(v)) {
      resultEl.innerHTML = renderError("validation_error",
        "Field " + k + " is not a finite number.");
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
      resultEl.innerHTML = renderError(null, "unexpected server response (" + r.status + ")");
    }
  } catch (err) {
    stopProgress();
    resultEl.innerHTML = renderNetworkError();
  }
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

checkEngine();
