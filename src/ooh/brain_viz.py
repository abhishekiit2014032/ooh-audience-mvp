"""Animated "data sources -> engine -> analytics" diagram, rendered as a self-contained HTML page.

The diagram reads only from :mod:`ooh.sources`, so every arrow matches the code. Particles flow
along live connections; their count and speed follow the source's confidence score. Sources
that are not connected are drawn dashed with no particles. Hover a source or an output to trace
it; click to pin; click the background to release.
"""

from __future__ import annotations

import json

from .sources import ENGINE_OUTPUTS, OUTPUTS, engine_status, registry


def diagram_data() -> dict:
    return {
        "sources": [s.to_dict() for s in registry()],
        "engine": engine_status(),
        "outputs": [{"id": k, "name": v, "engine": "ai" if k in ENGINE_OUTPUTS["ai"] else "geo"}
                    for k, v in OUTPUTS.items()],
    }


def brain_html(data: dict | None = None) -> str:
    payload = json.dumps(data or diagram_data())
    return _TEMPLATE.replace("__DATA__", payload)


_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root { --bg:#0e1117; --card:#161b26; --line:#2a3242; --text:#e6e9ef; --muted:#8b93a7;
          --geo:#4C9AFF; --ai:#a78bfa; --live:#36B37E; --cached:#4C9AFF; --configured:#22b8cf;
          --ondemand:#22b8cf; --sample:#F5A524; --off:#5b6375; }
  html,body { margin:0; background:var(--bg); color:var(--text);
              font-family: "Source Sans Pro","Source Sans 3",-apple-system,Segoe UI,Roboto,sans-serif; }
  svg { width:100%; height:auto; display:block; }
  .card rect.bg { fill:var(--card); stroke:var(--line); stroke-width:1; transition: stroke .2s, fill .2s; }
  .card:hover rect.bg, .card.focus rect.bg { stroke:#c9d4ff; fill:#1b2232; }
  .card { cursor:pointer; transition: opacity .25s; }
  .name { font-size:14px; font-weight:600; fill:var(--text); }
  .sub { font-size:11px; fill:var(--muted); }
  .score { font-size:13px; font-weight:700; fill:var(--text); }
  .edge { fill:none; stroke-width:1.6; opacity:.45; transition: opacity .25s, stroke-width .25s; }
  .edge.off { stroke-dasharray:4 5; opacity:.35; }
  .edge.ctx { stroke-dasharray:2 4; }
  .dim { opacity:.12 !important; }
  .hl { opacity:1 !important; stroke-width:2.6 !important; }
  .particle { transition: opacity .25s; }
  .lobe-label { font-size:15px; font-weight:700; fill:#fff; text-anchor:middle; pointer-events:none; }
  .lobe-sub { font-size:11px; fill:#dfe6ff; text-anchor:middle; opacity:.85; pointer-events:none; }
  .col-title { font-size:12px; letter-spacing:.12em; fill:var(--muted); font-weight:700; }
  .pulse { animation: pulse 1.8s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
  @keyframes pulse { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:.35; transform:scale(1.6); } }
  .breathe { animation: breathe 4s ease-in-out infinite; transform-origin: 600px 380px; }
  @keyframes breathe { 0%,100% { transform:scale(1); } 50% { transform:scale(1.025); } }
  .ring { transition: stroke-dashoffset 1.2s cubic-bezier(.2,.8,.2,1); }
  .neuron { transition: opacity .4s, r .4s; }
  #tip { position:fixed; pointer-events:none; max-width:330px; background:#1b2232; border:1px solid #33405a;
         border-radius:10px; padding:10px 12px; font-size:12.5px; line-height:1.45; box-shadow:0 10px 30px rgba(0,0,0,.5);
         opacity:0; transform:translateY(4px); transition: opacity .15s, transform .15s; z-index:5; }
  #tip.show { opacity:1; transform:none; }
  #tip h4 { margin:0 0 4px; font-size:14px; }
  #tip .row { display:flex; justify-content:space-between; gap:12px; color:var(--muted); }
  #tip .bar { height:5px; background:#2a3242; border-radius:3px; margin:2px 0 5px; overflow:hidden; }
  #tip .bar i { display:block; height:100%; background:var(--geo); }
  #tip .tag { display:inline-block; border-radius:4px; padding:0 6px; font-size:10.5px; font-weight:700; margin-right:4px; }
  @media (prefers-reduced-motion: reduce) { .pulse,.breathe { animation:none; } .ring { transition:none; } }
</style></head>
<body>
<svg id="viz" viewBox="0 0 1200 780" role="img" aria-label="Data sources feeding the audience engine and its analytics"></svg>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("viz");
const tip = document.getElementById("tip");
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const STATUS_COLOR = {"live":"var(--live)","cached":"var(--cached)","configured":"var(--configured)",
  "on demand":"var(--ondemand)","sample":"var(--sample)","not connected":"var(--off)"};
const LABEL_COLOR = {"VERIFIED":["#d1e7dd","#0f5132"],"ESTIMATE":["#cfe2ff","#084298"],
  "ASSUMPTION":["#fff3cd","#664d03"],"SAMPLE":["#f8d7da","#842029"],"CONCEPT":["#e2e3e5","#41464b"]};

function el(tag, attrs={}, parent=svg) {
  const e = document.createElementNS(NS, tag);
  for (const [k,v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e); return e;
}
function text(parent, x, y, str, cls, extra={}) { const t = el("text", {x, y, class:cls, ...extra}, parent); t.textContent = str; return t; }

// ---------- defs: gradients, glow, clip for hemispheres
const defs = el("defs");
defs.innerHTML = `
  <radialGradient id="gGeo" cx="40%" cy="40%" r="75%"><stop offset="0" stop-color="#7fb6ff"/><stop offset=".55" stop-color="#2f6fd6"/><stop offset="1" stop-color="#14306b"/></radialGradient>
  <radialGradient id="gAi" cx="60%" cy="40%" r="75%"><stop offset="0" stop-color="#d4c4ff"/><stop offset=".55" stop-color="#8b5cf6"/><stop offset="1" stop-color="#3b1d82"/></radialGradient>
  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="soft"><feGaussianBlur stdDeviation="2"/></filter>
  <clipPath id="clipL"><rect x="0" y="0" width="596" height="780"/></clipPath>
  <clipPath id="clipR"><rect x="604" y="0" width="600" height="780"/></clipPath>`;

// ---------- layout
const SRC_X = 18, SRC_W = 262, OUT_X = 925, OUT_W = 257, CX = 600, CY = 380;
const sources = DATA.sources, outputs = DATA.outputs;
const srcY = i => 70 + i * ((740 - 70) / (sources.length - 1));
const outY = i => 95 + i * ((690 - 95) / (outputs.length - 1));
const outIndex = Object.fromEntries(outputs.map((o, i) => [o.id, i]));

text(svg, SRC_X, 30, "DATA SOURCES", "col-title");
text(svg, CX, 30, "AUDIENCE ENGINE", "col-title", {"text-anchor":"middle"});
text(svg, OUT_X, 30, "ANALYTICS", "col-title");

const gEdges = el("g"), gParticles = el("g"), gBrain = el("g"), gCards = el("g");

// ---------- brain: two hemispheres from overlapping lobes
const lobes = [[520,300,72],[468,365,74],[497,447,70],[560,470,58],[572,330,74],[556,398,70],[520,380,60]];
const brain = el("g", {class: reduce ? "" : "breathe"}, gBrain);
el("ellipse", {cx:CX, cy:CY, rx:205, ry:170, fill:"#3d5bd9", opacity:.18, filter:"url(#glow)"}, brain);
const L = el("g", {"clip-path":"url(#clipL)"}, brain), R = el("g", {"clip-path":"url(#clipR)"}, brain);
lobes.forEach(([x,y,r]) => {
  el("circle", {cx:x, cy:y, r, fill:"url(#gGeo)"}, L);
  el("circle", {cx:2*CX - x, cy:y, r, fill:"url(#gAi)"}, R);
});
// gyri: soft folds
const folds = ["M470 330 q30 -25 60 0 t60 0","M450 390 q35 -22 70 0 t65 0","M470 450 q30 -20 60 0 t55 0",
               "M500 300 q20 30 0 60","M545 420 q-18 26 6 52"];
folds.forEach(d => { el("path", {d, fill:"none", stroke:"#cfe0ff", "stroke-width":2.2, opacity:.35, "stroke-linecap":"round"}, L);
  el("path", {d, fill:"none", stroke:"#ece4ff", "stroke-width":2.2, opacity:.35, "stroke-linecap":"round",
              transform:`translate(${2*CX},0) scale(-1,1)`}, R); });
// neurons that fire
const neurons = [];
function rnd(a,b){ return a + Math.random()*(b-a); }
for (let i = 0; i < 26; i++) {
  const left = i < 18;
  const x = left ? rnd(440, 585) : rnd(615, 735), y = rnd(300, 470);
  neurons.push(el("circle", {cx:x, cy:y, r:2.2, fill:"#fff", opacity:.45, class:"neuron"}, left ? L : R));
}
if (!reduce) setInterval(() => {
  const n = neurons[Math.floor(Math.random()*neurons.length)];
  n.setAttribute("opacity", 1); n.setAttribute("r", 4.2);
  setTimeout(() => { n.setAttribute("opacity", .45); n.setAttribute("r", 2.2); }, 420);
}, 160);
// hemisphere labels
const eg = DATA.engine;
text(brain, 515, 372, "Geospatial", "lobe-label"); text(brain, 515, 391, "reach model", "lobe-label");
text(brain, 515, 410, "counts every number", "lobe-sub");
text(brain, 688, 372, "Claude", "lobe-label");
text(brain, 688, 391, eg.ai.status === "active" ? "explains, sorts news" : "templates (no key)", "lobe-sub");
// computed numbers -> Claude arc
const arc = el("path", {id:"arc", d:"M545 262 C 580 205, 620 205, 655 262", fill:"none", stroke:"#c4b5fd",
  "stroke-width":1.8, "stroke-dasharray":"3 4", opacity:.8}, gBrain);
text(gBrain, CX, 214, "computed numbers only", "sub", {"text-anchor":"middle"});

// ---------- edges
const edgeEls = [];   // {el, from, to, kind}
function curve(x1,y1,x2,y2) { const mx = (x1 + x2) / 2; return `M${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`; }
function particles(pathEl, color, n, dur, group) {
  if (reduce || n <= 0) return [];
  const id = pathEl.getAttribute("id"), out = [];
  for (let k = 0; k < n; k++) {
    const c = el("circle", {r:3, fill:color, class:"particle", filter:"url(#soft)"}, group);
    const a = el("animateMotion", {dur:`${dur}s`, repeatCount:"indefinite", begin:`${-(k*dur/n).toFixed(2)}s`}, c);
    el("mpath", {href:`#${id}`}, a);
    const core = el("circle", {r:1.6, fill:"#fff", class:"particle"}, group);
    const a2 = el("animateMotion", {dur:`${dur}s`, repeatCount:"indefinite", begin:`${-(k*dur/n).toFixed(2)}s`}, core);
    el("mpath", {href:`#${id}`}, a2);
    out.push(c, core);
  }
  return out;
}

sources.forEach((s, i) => {
  const y = srcY(i);
  const toAi = s.engine === "ai";
  const tx = toAi ? 640 : 438, ty = toAi ? 470 : CY + (y - CY) * 0.33;
  const d = toAi ? `M${SRC_X+SRC_W} ${y} C 470 ${y}, 520 560, ${tx} ${ty}` : curve(SRC_X + SRC_W, y, tx, ty);
  const color = STATUS_COLOR[s.status] || "var(--off)";
  const p = el("path", {id:`e-src-${s.id}`, d, stroke:color,
    class:`edge ${s.status === "not connected" ? "off" : ""} ${s.context_only ? "ctx" : ""}`}, gEdges);
  const live = s.status !== "not connected";
  const n = live ? 1 + Math.round(s.score / 30) : 0;
  const dur = (5.2 - 3.0 * s.score / 100).toFixed(2);
  const parts = particles(p, color, n, dur, gParticles);
  edgeEls.push({el:p, parts, src:s.id, engine:s.engine});
});
outputs.forEach((o, i) => {
  const y = outY(i);
  const fromAi = o.engine === "ai";
  const sx = fromAi ? 770 : 760, sy = CY + (y - CY) * 0.35;
  const p = el("path", {id:`e-out-${o.id}`, d:curve(sx, sy, OUT_X, y), stroke: fromAi ? "var(--ai)" : "var(--geo)",
    class:"edge"}, gEdges);
  const parts = particles(p, fromAi ? "#c4b5fd" : "#8fc0ff", 2, 3.2, gParticles);
  edgeEls.push({el:p, parts, out:o.id, engine:o.engine});
});
particles(arc, "#e9d5ff", 2, 2.4, gParticles);

// ---------- source cards with score rings
const cards = {};
sources.forEach((s, i) => {
  const y = srcY(i);
  const g = el("g", {class:"card", transform:`translate(${SRC_X},${y - 25})`}, gCards);
  el("rect", {class:"bg", width:SRC_W, height:50, rx:10}, g);
  const color = STATUS_COLOR[s.status] || "var(--off)";
  el("circle", {cx:14, cy:17, r:4.5, fill:color, class: (s.status === "live" && !reduce) ? "pulse" : ""}, g);
  text(g, 26, 21, s.name.length > 26 ? s.name.slice(0, 25) + "…" : s.name, "name");
  text(g, 14, 39, `${s.status}${s.phase !== "MVP" ? " · " + s.phase : ""}${s.context_only ? " · context only" : ""}`, "sub");
  // score ring
  const r = 15, C = 2 * Math.PI * r;
  el("circle", {cx:SRC_W - 26, cy:25, r, fill:"none", stroke:"#2a3242", "stroke-width":4}, g);
  const ring = el("circle", {cx:SRC_W - 26, cy:25, r, fill:"none", stroke:color, "stroke-width":4,
    "stroke-dasharray":C, "stroke-dashoffset":C, "stroke-linecap":"round", class:"ring",
    transform:`rotate(-90 ${SRC_W - 26} 25)`}, g);
  requestAnimationFrame(() => setTimeout(() => ring.setAttribute("stroke-dashoffset", C * (1 - s.score / 100)), 80 + i * 60));
  text(g, SRC_W - 26, 29.5, String(s.score), "score", {"text-anchor":"middle"});
  cards[`s:${s.id}`] = g;
  g.addEventListener("mouseenter", ev => { if (!pinned) focusSource(s.id); showTip(ev, sourceTip(s)); });
  g.addEventListener("mousemove", moveTip);
  g.addEventListener("mouseleave", () => { if (!pinned) clearFocus(); hideTip(); });
  g.addEventListener("click", ev => { ev.stopPropagation(); pinned = pinned === `s:${s.id}` ? null : `s:${s.id}`;
    pinned ? focusSource(s.id) : clearFocus(); });
});
outputs.forEach((o, i) => {
  const y = outY(i);
  const g = el("g", {class:"card", transform:`translate(${OUT_X},${y - 22})`}, gCards);
  el("rect", {class:"bg", width:OUT_W, height:44, rx:10}, g);
  el("rect", {x:0, y:8, width:4, height:28, rx:2, fill: o.engine === "ai" ? "var(--ai)" : "var(--geo)"}, g);
  text(g, 16, 27, o.name, "name");
  cards[`o:${o.id}`] = g;
  const feeders = sources.filter(s => s.feeds.includes(o.id));
  g.addEventListener("mouseenter", ev => { if (!pinned) focusOutput(o.id); showTip(ev, outputTip(o, feeders)); });
  g.addEventListener("mousemove", moveTip);
  g.addEventListener("mouseleave", () => { if (!pinned) clearFocus(); hideTip(); });
  g.addEventListener("click", ev => { ev.stopPropagation(); pinned = pinned === `o:${o.id}` ? null : `o:${o.id}`;
    pinned ? focusOutput(o.id) : clearFocus(); });
});

// ---------- focus logic
let pinned = null;
function setFocus(srcIds, outIds) {
  edgeEls.forEach(e => {
    const on = !!((e.src && srcIds.has(e.src)) || (e.out && outIds.has(e.out)));
    e.el.classList.toggle("hl", on); e.el.classList.toggle("dim", !on);
    e.parts.forEach(p => p.style.opacity = on ? 1 : .08);
  });
  Object.entries(cards).forEach(([k, g]) => {
    const [t, id] = k.split(":");
    const on = !!((t === "s" && srcIds.has(id)) || (t === "o" && outIds.has(id)));
    g.classList.toggle("dim", !on); g.classList.toggle("focus", on);
  });
}
function focusSource(id) { const s = sources.find(x => x.id === id); setFocus(new Set([id]), new Set(s.feeds)); }
function focusOutput(id) { setFocus(new Set(sources.filter(s => s.feeds.includes(id)).map(s => s.id)), new Set([id])); }
function clearFocus() {
  edgeEls.forEach(e => { e.el.classList.remove("hl", "dim"); e.parts.forEach(p => p.style.opacity = 1); });
  Object.values(cards).forEach(g => g.classList.remove("dim", "focus"));
}
svg.addEventListener("click", () => { pinned = null; clearFocus(); });

// ---------- tooltip
function tag(label) { const [bg, fg] = LABEL_COLOR[label] || ["#e2e3e5", "#41464b"];
  return `<span class="tag" style="background:${bg};color:${fg}">${label}</span>`; }
function bar(name, v, w) { return `<div class="row"><span>${name} <small>×${w}</small></span><span>${v.toFixed(2)}</span></div>
  <div class="bar"><i style="width:${Math.round(v*100)}%"></i></div>`; }
function sourceTip(s) {
  const b = s.breakdown;
  return `<h4>${s.name}</h4><div style="color:var(--muted);margin-bottom:6px">${s.provider}</div>
    <div style="margin-bottom:6px">${s.what}</div>
    ${tag(s.label)} <b>${s.status}</b> · ${s.status_note}
    <div style="margin:8px 0 4px;font-size:13px"><b>Confidence ${s.score}</b> / 100 · potential ${s.potential}</div>
    ${bar("Provenance", b.provenance, .40)}${bar("Directness", b.directness, .35)}${bar("Freshness", b.freshness, .25)}
    <div class="row"><span>Status factor</span><span>${b.status_factor.toFixed(2)}</span></div>
    <div style="margin-top:6px">Feeds: ${s.feeds_names.join(", ")}${s.context_only ? " (context, not reach)" : ""}</div>
    <div style="margin-top:4px;color:var(--muted)">Upgrade: ${s.upgrade}</div>`;
}
function outputTip(o, feeders) {
  const live = feeders.filter(s => s.status !== "not connected");
  const avg = live.length ? Math.round(live.reduce((a, s) => a + s.score, 0) / live.length) : 0;
  return `<h4>${o.name}</h4><div style="color:var(--muted);margin-bottom:6px">Built by the ${o.engine === "ai" ? "Claude" : "geospatial reach model"} half</div>
    ${feeders.map(s => `<div class="row"><span>${s.name}</span><span>${s.status === "not connected" ? "—" : s.score}</span></div>`).join("")}
    <div style="margin-top:6px">Mean confidence of connected inputs: <b>${avg}</b></div>`;
}
function showTip(ev, html) { tip.innerHTML = html; tip.classList.add("show"); moveTip(ev); }
function moveTip(ev) {
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > window.innerWidth) x = ev.clientX - w - pad;
  if (y + h > window.innerHeight) y = Math.max(4, window.innerHeight - h - 4);
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { tip.classList.remove("show"); }

// ---------- legend
const lg = el("g", {transform:"translate(330,742)"});
[["live","live"],["cached","cached"],["configured","configured / on demand"],["sample","sample (placeholder)"],["not connected","not connected"]]
  .forEach(([k, label], i) => { el("circle", {cx:i*150, cy:0, r:5, fill:STATUS_COLOR[k]}, lg); text(lg, i*150 + 10, 4, label, "sub"); });
text(svg, 330, 766, "Particle count and speed follow the confidence score. Hover to trace a source or an output; click to pin.", "sub");
</script></body></html>
"""
