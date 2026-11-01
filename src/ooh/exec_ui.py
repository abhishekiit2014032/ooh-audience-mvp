"""HTML blocks for the executive pages of the dashboard (white theme, animated, self-contained).

Each function takes plain data (dicts and lists built by the app from ``Results``) and returns one
HTML document for ``streamlit.components.v1.html``. All interaction (toggles, sorting, the budget
slider) runs in the browser, so it responds instantly without a Streamlit rerun. The numbers
themselves always come from the pipeline; nothing here calculates reach.
"""

from __future__ import annotations

import json

# Billboard identity colours (categorical slots 1-4 of the validated reference palette, fixed order).
FACE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]

# Plain-language trust levels for the label badges.
TRUST = {
    "VERIFIED": ("Solid", "Published by an official or named source."),
    "ESTIMATE": ("Good estimate", "Calculated from verified data plus a stated assumption."),
    "ASSUMPTION": ("Our assumption", "A parameter we chose; analysts can change it."),
    "SAMPLE": ("Directional", "Built partly on placeholder inputs (Meta audience, metro ridership, play logs) "
                              "until real values are entered."),
    "CONCEPT": ("Idea stage", "Needs a partner or further validation."),
}


def people(x: float) -> str:
    """Executive rounding for head counts: 1.1M / 273k / 9.5k / 840."""
    x = max(0.0, float(x))
    if x >= 1e6:
        return f"{x / 1e6:.1f}M"
    if x >= 1e4:
        return f"{x / 1e3:.0f}k"
    if x >= 1e3:
        return f"{x / 1e3:.1f}k"
    return f"{x:,.0f}"


def aed(x: float) -> str:
    return f"AED {people(x)}"


_BASE_CSS = r"""
:root { --ink:#1d1b2e; --ink2:#55536a; --muted:#8a889c; --line:#ecebf3; --soft:#f7f6fc; --card:#ffffff;
        --accent:#6250d6; --accent2:#8b7cf0; --accent-soft:#efedfc; --good:#0ca30c; --good-text:#0a7d0a;
        --warn:#fab219; --warn-text:#8a5a00; --crit:#d03b3b; --shadow:0 1px 2px rgba(29,27,46,.06), 0 6px 20px rgba(29,27,46,.06);
        --shadow-up:0 2px 4px rgba(29,27,46,.06), 0 14px 34px rgba(98,80,214,.16); }
* { box-sizing:border-box; }
html, body { margin:0; padding:0; background:transparent; color:var(--ink);
             font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; -webkit-font-smoothing:antialiased; }
body { padding:4px 4px 10px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:18px; box-shadow:var(--shadow);
        transition:transform .2s ease, box-shadow .2s ease, border-color .2s ease; }
.lift:hover { transform:translateY(-3px); box-shadow:var(--shadow-up); border-color:#dcd7fb; }
.chip { display:inline-flex; align-items:center; gap:5px; border-radius:999px; padding:3px 10px; font-size:12px;
        font-weight:600; background:var(--soft); color:var(--ink2); border:1px solid var(--line); white-space:nowrap; }
.chip.good { background:#e9f7e9; color:var(--good-text); border-color:#cdeccd; }
.chip.warn { background:#fff6e0; color:var(--warn-text); border-color:#fbe3a6; }
.chip.crit { background:#fdeaea; color:#a42a2a; border-color:#f6caca; }
.chip.accent { background:var(--accent-soft); color:var(--accent); border-color:#dcd7fb; }
.trust { position:relative; cursor:help; }
.trust .pop { position:absolute; z-index:20; top:calc(100% + 8px); right:0; width:260px; background:#fff; color:var(--ink2);
              border:1px solid var(--line); border-radius:12px; padding:10px 12px; font-size:12px; font-weight:500;
              line-height:1.45; box-shadow:var(--shadow-up); white-space:normal; opacity:0; transform:translateY(-4px);
              pointer-events:none; transition:opacity .15s, transform .15s; }
.trust:hover .pop, .trust:focus .pop { opacity:1; transform:none; }
.muted { color:var(--muted); }
.fade { opacity:0; transform:translateY(10px); animation:fadeUp .5s cubic-bezier(.2,.8,.2,1) forwards; }
@keyframes fadeUp { to { opacity:1; transform:none; } }
@keyframes pop { 0% { transform:scale(.6); opacity:0; } 70% { transform:scale(1.08); } 100% { transform:scale(1); opacity:1; } }
@keyframes shake { 10%,90% { transform:translateX(-1px); } 20%,80% { transform:translateX(2px); }
                   30%,50%,70% { transform:translateX(-4px); } 40%,60% { transform:translateX(4px); } }
@keyframes wiggle { 0%,100% { transform:rotate(0); } 25% { transform:rotate(-8deg); } 75% { transform:rotate(8deg); } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation:none !important; transition:none !important; }
  .fade { opacity:1; transform:none; } }
"""

_BASE_JS = r"""
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
function fmtP(x) { x = Math.max(0, x); if (x >= 1e6) return (x / 1e6).toFixed(1) + 'M';
  if (x >= 1e4) return Math.round(x / 1e3) + 'k'; if (x >= 1e3) return (x / 1e3).toFixed(1) + 'k';
  return Math.round(x).toLocaleString(); }
function fmtA(x) { return 'AED ' + fmtP(x); }
function tween(el, to, fmt, ms) {
  ms = ms || 750; const from = el.dataset.v !== undefined ? +el.dataset.v : (reduce ? to : to * 0.55);
  el.dataset.v = to; if (reduce || from === to) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  function step(t) { const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); }
  requestAnimationFrame(step);
}
let _box = null;
function fit() { try { const f = window.frameElement; if (!f) return;
  const h = Math.ceil(document.body.getBoundingClientRect().height + 2) + 'px';
  f.style.height = h; _box = f.closest('[data-testid="stElementContainer"]');
  if (_box) { _box.style.height = h; _box.style.flex = '0 0 ' + h; } } catch (e) {} }
// Streamlit reuses the wrapper for whatever renders next in this slot: hand its size back when we leave.
function release() { if (_box) { _box.style.height = ''; _box.style.flex = ''; } }
window.addEventListener('pagehide', release); window.addEventListener('unload', release);
new ResizeObserver(fit).observe(document.body); window.addEventListener('load', fit); setTimeout(fit, 60);
// Safety net: never leave an entrance animation half-way (e.g. if the frame was hidden while it ran).
setTimeout(() => { try { document.getAnimations().forEach(a => { const t = a.effect && a.effect.getTiming();
  if (t && t.iterations !== Infinity && a.playState !== 'finished') a.finish(); }); } catch (e) {} fit(); }, 2500);
"""


def _doc(css: str, body: str, js: str, data: dict) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'><style>" + _BASE_CSS + css + "</style></head><body>"
            + body + "<script>" + _BASE_JS + "const D = " + json.dumps(data) + ";\n" + js + "</script></body></html>")


# --------------------------------------------------------------------------- page header


def header_html(eyebrow: str, title: str, subtitle: str) -> str:
    """Page title block (plain HTML for st.markdown)."""
    return (f"<div class='ooh-head'><div class='ooh-eyebrow'>{eyebrow}</div>"
            f"<h1 class='ooh-title'>{title}</h1><p class='ooh-sub'>{subtitle}</p></div>")


# --------------------------------------------------------------------------- decision: plan builder


_DECISION_CSS = r"""
.dec { display:grid; grid-template-columns:1.05fr 1fr; gap:18px; }
@media (max-width:820px) { .dec { grid-template-columns:1fr; } }
.hero { padding:22px 24px; background:radial-gradient(120% 140% at 0% 0%, #f1eeff 0%, #ffffff 55%), #fff; position:relative; overflow:hidden; }
.hero::after { content:""; position:absolute; right:-60px; top:-60px; width:200px; height:200px; border-radius:50%;
               background:radial-gradient(circle, rgba(98,80,214,.14), rgba(98,80,214,0) 70%); animation:float 7s ease-in-out infinite; }
@keyframes float { 50% { transform:translate(-18px, 14px) scale(1.08); } }
.eyebrow { display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:12.5px; font-weight:700;
           letter-spacing:.06em; text-transform:uppercase; color:var(--accent); }
.eyebrow .chip { text-transform:none; letter-spacing:0; }
h2 { margin:10px 0 6px; font-size:25px; line-height:1.2; letter-spacing:-.01em; }
h2 .fc { display:inline-block; animation:pop .4s cubic-bezier(.2,.8,.2,1) both; }
h2 .fc i { display:inline-block; width:12px; height:12px; border-radius:50%; margin:0 5px 2px 2px; vertical-align:middle; }
.bigrow { display:flex; align-items:flex-end; gap:12px; margin-top:8px; }
.big { font-size:60px; font-weight:800; line-height:1; letter-spacing:-.03em; color:var(--accent);
       background:linear-gradient(90deg, #6250d6, #2a78d6); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
.bigsub { font-size:14px; color:var(--ink2); line-height:1.3; padding-bottom:6px; }
.range { margin-top:6px; font-size:13px; color:var(--muted); }
.stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-top:16px; }
.stat { background:rgba(255,255,255,.75); border:1px solid var(--line); border-radius:14px; padding:10px 12px; }
.stat .k { font-size:11.5px; color:var(--muted); font-weight:600; }
.stat .v { font-size:20px; font-weight:750; margin-top:2px; }
.stat .s { font-size:11px; color:var(--muted); }
.bud { margin-top:16px; }
.budtrack { position:relative; height:12px; border-radius:999px; background:var(--soft); border:1px solid var(--line); overflow:hidden; }
.budfill { height:100%; width:0; border-radius:999px; background:linear-gradient(90deg, #8b7cf0, #6250d6);
           transition:width .7s cubic-bezier(.2,.8,.2,1), background .3s; }
.budfill.over { background:linear-gradient(90deg, #ec835a, #d03b3b); }
.budlbl { display:flex; justify-content:space-between; font-size:12px; color:var(--ink2); margin-top:6px; }
.msg { margin-top:12px; font-size:13.5px; line-height:1.45; padding:10px 12px; border-radius:12px; background:var(--soft);
       border:1px solid var(--line); color:var(--ink2); min-height:42px; }
.msg.bad { background:#fdeaea; border-color:#f6caca; color:#8f2323; animation:shake .45s; }
.msg.good { background:#e9f7e9; border-color:#cdeccd; color:#0a6a0a; }
.builder { padding:20px 20px 18px; }
.bhead { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
.bhead b { font-size:16px; }
.hint { font-size:12px; color:var(--muted); margin-top:2px; }
button.reset { border:1px solid #dcd7fb; background:var(--accent-soft); color:var(--accent); font-weight:700; font-size:12.5px;
               border-radius:999px; padding:6px 12px; cursor:pointer; transition:transform .15s, background .15s; }
button.reset:hover { transform:translateY(-1px) rotate(-2deg); background:#e4e0fb; }
.faces { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:14px; }
.face { position:relative; text-align:left; font:inherit; color:inherit; cursor:pointer; background:#fff; border:1.5px solid var(--line);
        border-radius:16px; padding:12px 12px 11px; transition:transform .18s, box-shadow .18s, border-color .18s, background .18s, opacity .18s; }
.face:hover { transform:translateY(-3px); box-shadow:var(--shadow-up); }
.face:active { transform:scale(.97); }
.face:not(.on) { opacity:.62; background:#fbfbfd; }
.face.on { border-color:var(--c); box-shadow:0 0 0 3px color-mix(in srgb, var(--c) 18%, transparent); }
.ftop { display:flex; align-items:center; gap:7px; }
.dot { width:11px; height:11px; border-radius:50%; background:var(--c); flex:none; }
.ftop b { font-size:15px; }
.tick { margin-left:auto; width:22px; height:22px; border-radius:50%; border:1.5px solid var(--line); display:grid; place-items:center;
        font-size:13px; color:#fff; transition:background .2s, border-color .2s, transform .25s; }
.face.on .tick { background:var(--c); border-color:var(--c); transform:rotate(360deg); }
.fname { font-size:12px; color:var(--muted); margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fnum { font-size:22px; font-weight:780; margin-top:6px; letter-spacing:-.01em; }
.fnum small { font-size:11.5px; font-weight:600; color:var(--muted); letter-spacing:0; }
.fsub { font-size:12px; color:var(--ink2); margin-top:2px; }
.ribbon { position:absolute; top:-9px; right:12px; font-size:10.5px; font-weight:800; color:#5a3d00; background:#ffe7a3;
          border:1px solid #f7d36b; border-radius:999px; padding:1px 8px; transform:scale(0); transition:transform .3s cubic-bezier(.2,.8,.2,1.4); }
.face.pick .ribbon { transform:scale(1); }
.slider { margin-top:16px; }
.srow { display:flex; justify-content:space-between; align-items:baseline; font-size:13px; color:var(--ink2); }
.srow b { font-size:16px; color:var(--ink); }
input[type=range] { -webkit-appearance:none; appearance:none; width:100%; height:8px; border-radius:999px; margin:10px 0 4px;
  background:linear-gradient(90deg, var(--accent) var(--p,50%), var(--soft) var(--p,50%)); border:1px solid var(--line); outline:none; }
input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; width:24px; height:24px; border-radius:50%; background:#fff;
  border:3px solid var(--accent); box-shadow:0 3px 10px rgba(98,80,214,.35); cursor:grab; transition:transform .15s; }
input[type=range]::-webkit-slider-thumb:hover { transform:scale(1.15); }
input[type=range]::-moz-range-thumb { width:20px; height:20px; border-radius:50%; background:#fff; border:3px solid var(--accent); cursor:grab; }
"""

_DECISION_BODY = r"""
<div class="dec">
  <section class="hero card fade">
    <div class="eyebrow"><span id="mode">🎯 Our recommendation</span>
      <span class="chip warn trust" tabindex="0" id="trust">◔ <span id="trustname"></span><span class="pop" id="trustpop"></span></span></div>
    <h2 id="headline"></h2>
    <div class="bigrow"><div class="big" id="reach">0</div><div class="bigsub">car-interested people<br>reached every month</div></div>
    <div class="range" id="range"></div>
    <div class="stats">
      <div class="stat"><div class="k">Monthly spend</div><div class="v" id="spend">–</div><div class="s" id="spends"></div></div>
      <div class="stat"><div class="k">Cost per person</div><div class="v" id="cpp">–</div><div class="s">per month</div></div>
      <div class="stat"><div class="k">Double-counting removed</div><div class="v" id="dup">–</div><div class="s">people on 2+ boards</div></div>
    </div>
    <div class="bud"><div class="budtrack"><div class="budfill" id="fill"></div></div>
      <div class="budlbl"><span id="budl"></span><span id="budr"></span></div></div>
    <div class="msg" id="msg"></div>
  </section>
  <section class="builder card fade" style="animation-delay:.08s">
    <div class="bhead"><div><b>Try your own mix</b><div class="hint">Tap a billboard to add or drop it</div></div>
      <button class="reset" id="reset">↺ Back to our pick</button></div>
    <div class="faces" id="faces"></div>
    <div class="slider"><div class="srow"><span>Monthly budget</span><b id="bv"></b></div>
      <input type="range" id="budget" aria-label="Monthly budget">
      <div class="hint">Move the budget and we re-run our pick for that amount</div></div>
  </section>
</div>
"""

_DECISION_JS = r"""
const F = D.faces, byId = Object.fromEntries(F.map(f => [f.id, f]));
let budget = D.budget, sel = new Set(D.picks[String(D.budget)] || []), custom = false;
document.getElementById('trustname').textContent = D.trust[0];
document.getElementById('trustpop').textContent = D.trust[1];
const facesEl = document.getElementById('faces');
F.forEach((f, i) => {
  const b = document.createElement('button');
  b.className = 'face fade'; b.style.setProperty('--c', f.color); b.style.animationDelay = (0.12 + i * 0.06) + 's';
  b.dataset.id = f.id;
  b.innerHTML = `<span class="ribbon">⭐ Our pick</span>
    <div class="ftop"><span class="dot"></span><b>${f.id}</b><span class="tick">✓</span></div>
    <div class="fname" title="${f.name}">${f.area} · ${f.type}</div>
    <div class="fnum">${fmtP(f.rel)} <small>people / month</small></div>
    <div class="fsub">${fmtA(f.cost)} · AED ${f.cpp.toFixed(2)} per person</div>`;
  b.onclick = () => { sel.has(f.id) ? sel.delete(f.id) : sel.add(f.id); custom = true; render(); };
  facesEl.appendChild(b);
});
const slider = document.getElementById('budget');
slider.min = 0; slider.max = D.budget_max; slider.step = D.step; slider.value = budget;
slider.oninput = () => { budget = +slider.value; sel = new Set(D.picks[String(budget)] || []); custom = false; render(); };
document.getElementById('reset').onclick = () => { sel = new Set(D.picks[String(budget)] || []); custom = false; render(); };

function key(s) { return [...s].sort().join(','); }
function list(ids) { return ids.length <= 1 ? ids.join('') : ids.slice(0, -1).join(', ') + ' and ' + ids[ids.length - 1]; }
function render() {
  const pickIds = D.picks[String(budget)] || [], pickSet = new Set(pickIds);
  const ids = F.map(f => f.id).filter(i => sel.has(i));
  const order = pickIds.filter(i => sel.has(i)).concat(ids.filter(i => !pickSet.has(i)));
  const cost = ids.reduce((a, i) => a + byId[i].cost, 0);
  const rel = ids.length ? D.subsets[key(sel)].rel : 0;
  const naive = ids.reduce((a, i) => a + byId[i].rel, 0);
  const lo = ids.reduce((a, i) => a + byId[i].rel_lo, 0), hi = ids.reduce((a, i) => a + byId[i].rel_hi, 0);
  const isPick = key(sel) === key(pickSet);
  const over = cost > budget;

  document.querySelectorAll('.face').forEach(b => {
    b.classList.toggle('on', sel.has(b.dataset.id)); b.classList.toggle('pick', pickSet.has(b.dataset.id));
    b.setAttribute('aria-pressed', sel.has(b.dataset.id)); });
  document.getElementById('mode').textContent = isPick ? '🎯 Our recommendation' : '✏️ Your plan';
  document.getElementById('headline').innerHTML = ids.length
    ? `Book ${order.length === F.length ? 'all four: ' : ''}${list(order.map(i => `<span class="fc"><i style="background:${byId[i].color}"></i>${i}</span>`))}`
    : 'No billboards picked yet';
  tween(document.getElementById('reach'), rel, fmtP);
  document.getElementById('range').textContent = ids.length
    ? `Likely between ${fmtP(rel * lo / naive)} and ${fmtP(rel * hi / naive)}, depending on how often people repeat the trip`
    : 'Tap a billboard on the right to start';
  tween(document.getElementById('spend'), cost, fmtA);
  document.getElementById('spends').textContent = `of ${fmtA(budget)} budget`;
  const cpp = document.getElementById('cpp');
  if (rel > 0) tween(cpp, cost / rel, x => 'AED ' + x.toFixed(2)); else { cpp.textContent = '–'; delete cpp.dataset.v; }
  tween(document.getElementById('dup'), naive - rel, fmtP);

  const fill = document.getElementById('fill');
  fill.style.width = Math.min(100, budget ? cost / budget * 100 : (cost ? 100 : 0)) + '%';
  fill.classList.toggle('over', over);
  document.getElementById('budl').textContent = over ? `${fmtA(cost - budget)} over budget` : `${fmtA(budget - cost)} left`;
  document.getElementById('budr').textContent = `Budget ${fmtA(budget)}`;
  document.getElementById('bv').textContent = fmtA(budget);
  slider.style.setProperty('--p', (budget / D.budget_max * 100) + '%');

  const msg = document.getElementById('msg'); msg.className = 'msg';
  const pickRel = pickIds.length ? D.subsets[key(pickSet)].rel : 0;
  const pickCost = pickIds.reduce((a, i) => a + byId[i].cost, 0);
  if (!ids.length) { msg.textContent = 'Pick at least one billboard to see the reach.'; }
  else if (over) { msg.className = 'msg bad'; msg.innerHTML = `⚠️ This mix is <b>${fmtA(cost - budget)} over budget</b>. Drop a billboard or raise the budget.`; }
  else if (isPick) {
    const left = budget - cost, rest = F.filter(f => !sel.has(f.id));
    const cheapest = rest.sort((a, b) => a.cost - b.cost)[0];
    msg.className = 'msg good';
    msg.innerHTML = rest.length === 0 ? `✅ Every billboard fits. ${fmtA(left)} of the budget is spare.`
      : left < cheapest.cost ? `✅ Best reach per dirham for this budget. The ${fmtA(left)} left over can't buy another board: the cheapest one left (${cheapest.id}) costs ${fmtA(cheapest.cost)}.`
      : `✅ Best reach per dirham for this budget. Adding more boards here would mostly reach people we already reach.`;
  } else if (rel < pickRel - 1) {
    msg.innerHTML = `💡 Our pick (${list(pickIds)}) reaches <b>${fmtP(pickRel - rel)} more people</b>` +
      (pickCost <= cost ? ` and costs ${fmtA(cost - pickCost)} less.` : ` for ${fmtA(pickCost - cost)} more.`);
  } else {
    msg.className = 'msg good';
    msg.innerHTML = `🙌 This mix reaches ${fmtP(rel - pickRel)} more people than our pick, for ${fmtA(cost - pickCost)} more spend (AED ${((cost - pickCost) / Math.max(1, rel - pickRel)).toFixed(2)} per extra person).`;
  }
  fit();
}
render();
"""


def decision_html(data: dict) -> str:
    return _doc(_DECISION_CSS, _DECISION_BODY, _DECISION_JS, data)


# --------------------------------------------------------------------------- decision: insight tiles


_INSIGHTS_CSS = r"""
.grid { display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; }
@media (max-width:820px) { .grid { grid-template-columns:1fr; } }
.tile { padding:16px 18px 16px; position:relative; }
.tile .q { font-size:12.5px; font-weight:700; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); display:flex; align-items:center; gap:6px; }
.tile .emo { font-size:18px; display:inline-block; }
.tile:hover .emo { animation:wiggle .5s; }
.tile .a { font-size:30px; font-weight:800; letter-spacing:-.02em; margin:8px 0 2px; }
.tile .a small { font-size:13px; font-weight:600; color:var(--ink2); letter-spacing:0; }
.tile p { margin:6px 0 0; font-size:13px; line-height:1.5; color:var(--ink2); }
.tile .row { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
.meter { display:flex; gap:5px; margin:12px 0 2px; }
.meter i { height:8px; flex:1; border-radius:999px; background:var(--line); transform-origin:left; }
.meter i.on { background:var(--warn); animation:grow .5s cubic-bezier(.2,.8,.2,1) both; }
@keyframes grow { from { transform:scaleX(0); } }
.why { margin-top:16px; padding:18px 20px; display:grid; grid-template-columns:auto 1fr; gap:14px; align-items:start; }
.why .big-emo { font-size:34px; line-height:1; }
.why h3 { margin:0 0 8px; font-size:17px; }
.why ul { margin:0; padding-left:18px; color:var(--ink2); font-size:13.5px; line-height:1.6; }
.why b { color:var(--ink); }
"""

_INSIGHTS_BODY = r"""<div class="grid" id="grid"></div><div id="why"></div>"""

_INSIGHTS_JS = r"""
const g = document.getElementById('grid');
D.tiles.forEach((t, i) => {
  const d = document.createElement('div'); d.className = 'tile card lift fade'; d.style.animationDelay = (i * 0.08) + 's';
  d.innerHTML = `<div class="q"><span class="emo">${t.emoji}</span>${t.q}</div>
    <div class="a">${t.a}${t.unit ? ` <small>${t.unit}</small>` : ''}</div>
    ${t.meter !== undefined ? `<div class="meter">${[0,1,2,3,4].map(k => `<i class="${k < t.meter ? 'on' : ''}" style="animation-delay:${.3 + k * .1}s"></i>`).join('')}</div>` : ''}
    <p>${t.text}</p><div class="row">${(t.chips || []).map(c => `<span class="chip ${c[1] || ''}">${c[0]}</span>`).join('')}</div>`;
  g.appendChild(d);
});
if (D.why) {
  const w = document.getElementById('why');
  w.innerHTML = `<div class="why card lift fade" style="animation-delay:.3s"><div class="big-emo">🤔</div>
    <div><h3>${D.why.title}</h3><ul>${D.why.points.map(p => `<li>${p}</li>`).join('')}</ul></div></div>`;
}
fit();
"""


def insights_html(data: dict) -> str:
    return _doc(_INSIGHTS_CSS, _INSIGHTS_BODY, _INSIGHTS_JS, data)


# --------------------------------------------------------------------------- league table


_LEAGUE_CSS = r"""
.bar { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
.seg { display:inline-flex; background:var(--soft); border:1px solid var(--line); border-radius:999px; padding:3px; gap:2px; }
.seg button { font:inherit; font-size:13px; font-weight:650; border:0; background:transparent; color:var(--ink2); padding:6px 14px;
              border-radius:999px; cursor:pointer; transition:background .2s, color .2s, box-shadow .2s; }
.seg button.on { background:#fff; color:var(--accent); box-shadow:0 2px 8px rgba(29,27,46,.10); }
.list { position:relative; display:flex; flex-direction:column; gap:12px; }
.row { display:grid; grid-template-columns:54px 1.35fr 1fr 1.6fr 1fr; gap:16px; align-items:center; padding:14px 18px; }
@media (max-width:860px) { .row { grid-template-columns:44px 1fr 1fr; } .row .reachcol { grid-column:2 / span 2; } .row .cppcol { grid-column:2 / span 2; } }
.medal { font-size:30px; text-align:center; line-height:1; }
.medal span { display:block; font-size:11px; color:var(--muted); font-weight:700; margin-top:3px; }
.row:hover .medal { animation:wiggle .5s; }
.id { display:flex; align-items:center; gap:8px; }
.id b { font-size:18px; }
.id .dot { width:12px; height:12px; border-radius:50%; background:var(--c); }
.nm { font-size:12.5px; color:var(--ink2); margin-top:2px; }
.tags { display:flex; gap:5px; flex-wrap:wrap; margin-top:7px; }
.k { font-size:11.5px; font-weight:650; color:var(--muted); }
.v { font-size:21px; font-weight:780; letter-spacing:-.01em; }
.v small { font-size:11.5px; color:var(--muted); font-weight:600; }
.track { position:relative; height:10px; margin-top:8px; background:var(--soft); border-radius:999px; }
.rng { position:absolute; top:3px; height:4px; border-radius:999px; background:color-mix(in srgb, var(--c) 30%, white); }
.fillb { position:absolute; left:0; top:0; height:10px; width:0; border-radius:999px; background:var(--c); transition:width .9s cubic-bezier(.2,.8,.2,1); }
.rtxt { font-size:11.5px; color:var(--muted); margin-top:5px; }
.cpp .v { color:var(--ink); }
.cppbar { height:6px; border-radius:999px; background:var(--soft); margin-top:8px; overflow:hidden; }
.cppbar i { display:block; height:100%; width:0; background:linear-gradient(90deg, #0ca30c, #fab219, #d03b3b); background-size:var(--bs,100%) 100%;
            border-radius:999px; transition:width .9s cubic-bezier(.2,.8,.2,1); }
.note { margin-top:14px; font-size:12.5px; color:var(--muted); line-height:1.5; }
"""

_LEAGUE_BODY = r"""
<div class="bar"><div class="seg" id="seg">
  <button data-k="value" class="on">💎 Best value</button><button data-k="reach">📣 Biggest audience</button><button data-k="cost">💰 Lowest price</button>
</div><span class="chip trust" tabindex="0">◔ <span id="tn"></span><span class="pop" id="tp"></span></span></div>
<div class="list" id="list"></div>
<div class="note" id="note"></div>
"""

_LEAGUE_JS = r"""
document.getElementById('tn').textContent = D.trust[0]; document.getElementById('tp').textContent = D.trust[1];
document.getElementById('note').innerHTML = D.note;
const L = document.getElementById('list'), maxHi = Math.max(...D.rows.map(r => r.rel_hi));
const cppMax = Math.max(...D.rows.map(r => r.cpp));
const els = {};
D.rows.forEach(r => {
  const d = document.createElement('div'); d.className = 'row card lift'; d.style.setProperty('--c', r.color);
  d.innerHTML = `<div class="medal"></div>
    <div><div class="id"><span class="dot"></span><b>${r.id}</b></div><div class="nm">${r.name}</div>
      <div class="tags">${r.tags.map(t => `<span class="chip ${t[1] || ''}">${t[0]}</span>`).join('')}</div></div>
    <div><div class="k">Monthly price</div><div class="v">${fmtA(r.cost)}</div><div class="rtxt">${r.type_note}</div></div>
    <div class="reachcol"><div class="k">Car-interested people / month</div><div class="v">${fmtP(r.rel)}</div>
      <div class="track"><div class="rng" style="left:${r.rel_lo / maxHi * 100}%;width:${(r.rel_hi - r.rel_lo) / maxHi * 100}%"></div><div class="fillb" data-w="${r.rel / maxHi * 100}"></div></div>
      <div class="rtxt">likely ${fmtP(r.rel_lo)} – ${fmtP(r.rel_hi)}</div></div>
    <div class="cpp cppcol"><div class="k">Cost per person</div><div class="v">AED ${r.cpp.toFixed(2)}</div>
      <div class="cppbar"><i data-w="${r.cpp / cppMax * 100}" style="--bs:${cppMax / r.cpp * 100}%"></i></div><div class="rtxt">${r.cpp_note}</div></div>`;
  L.appendChild(d); els[r.id] = d;
});
const medals = ['🥇', '🥈', '🥉', '🎗️'];
function sortBy(k) {
  const first = {}; Object.values(els).forEach(e => first[e.dataset.id || ''] = 0);
  const before = Object.fromEntries(Object.entries(els).map(([id, e]) => [id, e.getBoundingClientRect().top]));
  const rows = [...D.rows].sort((a, b) => k === 'value' ? a.cpp - b.cpp : k === 'reach' ? b.rel - a.rel : a.cost - b.cost);
  rows.forEach((r, i) => { const e = els[r.id]; L.appendChild(e);
    e.querySelector('.medal').innerHTML = `${medals[i]}<span>#${i + 1}</span>`; });
  if (!reduce) Object.entries(els).forEach(([id, e]) => {
    const dy = before[id] - e.getBoundingClientRect().top; if (!dy) return;
    e.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: 450, easing: 'cubic-bezier(.2,.8,.2,1)' }); });
}
document.querySelectorAll('#seg button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#seg button').forEach(x => x.classList.toggle('on', x === b)); sortBy(b.dataset.k); });
sortBy('value');
Object.values(els).forEach((e, i) => { e.classList.add('fade'); e.style.animationDelay = (i * .07) + 's'; });
setTimeout(() => document.querySelectorAll('[data-w]').forEach(x => x.style.width = x.dataset.w + '%'), reduce ? 0 : 250);
fit();
"""


def league_html(data: dict) -> str:
    return _doc(_LEAGUE_CSS, _LEAGUE_BODY, _LEAGUE_JS, data)


# --------------------------------------------------------------------------- audience


_AUD_CSS = r"""
.tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
.tab { font:inherit; font-size:13.5px; font-weight:700; border:1.5px solid var(--line); background:#fff; color:var(--ink2);
       border-radius:999px; padding:7px 14px; cursor:pointer; display:inline-flex; align-items:center; gap:7px;
       transition:transform .15s, border-color .2s, background .2s, color .2s; }
.tab:hover { transform:translateY(-2px); }
.tab .dot { width:10px; height:10px; border-radius:50%; background:var(--c); }
.tab.on { border-color:var(--c); background:color-mix(in srgb, var(--c) 10%, white); color:var(--ink); }
.persona { padding:18px 20px; display:grid; grid-template-columns:auto 1fr; gap:16px; align-items:center;
           background:radial-gradient(120% 160% at 0% 0%, color-mix(in srgb, var(--c) 12%, white), #fff 60%); }
.avatar { width:64px; height:64px; border-radius:20px; display:grid; place-items:center; font-size:34px; background:#fff;
          border:1px solid var(--line); box-shadow:var(--shadow); animation:pop .5s cubic-bezier(.2,.8,.2,1) both; }
.persona h3 { margin:0; font-size:19px; letter-spacing:-.01em; }
.persona p { margin:5px 0 0; color:var(--ink2); font-size:13.5px; line-height:1.5; }
.stats { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-top:14px; }
@media (max-width:820px) { .stats { grid-template-columns:repeat(2, 1fr); } }
.st { padding:14px 16px; }
.st .e { font-size:20px; }
.st .n { font-size:26px; font-weight:800; letter-spacing:-.02em; margin-top:4px; }
.st .l { font-size:12.5px; color:var(--ink2); line-height:1.35; margin-top:2px; }
.two { display:grid; grid-template-columns:1.5fr 1fr; gap:12px; margin-top:12px; }
@media (max-width:820px) { .two { grid-template-columns:1fr; } }
.panel { padding:16px 18px; }
.panel h4 { margin:0 0 2px; font-size:14.5px; }
.panel .sub { font-size:12px; color:var(--muted); margin-bottom:8px; }
svg { display:block; width:100%; height:auto; overflow:visible; }
.ages { display:flex; flex-direction:column; gap:7px; margin-top:6px; }
.age { display:grid; grid-template-columns:52px 1fr 38px; gap:8px; align-items:center; font-size:12.5px; color:var(--ink2); }
.age .t { height:12px; border-radius:999px; background:var(--soft); overflow:hidden; }
.age .t i { display:block; height:100%; width:0; border-radius:999px; background:var(--c); transition:width .8s cubic-bezier(.2,.8,.2,1); }
.age.hot .t i { background:var(--c); } .age:not(.hot) .t i { background:color-mix(in srgb, var(--c) 40%, white); }
.age b { color:var(--ink); text-align:right; }
.gender { display:flex; height:14px; border-radius:999px; overflow:hidden; margin-top:12px; gap:2px; }
.gender i { display:block; height:100%; transition:width .8s cubic-bezier(.2,.8,.2,1); width:50%; }
.glbl { display:flex; justify-content:space-between; font-size:12px; color:var(--ink2); margin-top:5px; }
.sowhat { margin-top:12px; padding:14px 18px; border-left:4px solid var(--accent); font-size:13.5px; line-height:1.55; color:var(--ink2); }
.sowhat b { color:var(--ink); }
.tip { position:absolute; pointer-events:none; background:#fff; border:1px solid var(--line); border-radius:10px; padding:6px 9px;
       font-size:12px; box-shadow:var(--shadow-up); opacity:0; transition:opacity .12s; white-space:nowrap; }
.chartwrap { position:relative; }
"""

_AUD_BODY = r"""
<div class="tabs" id="tabs"></div>
<div id="view"></div>
"""

_AUD_JS = r"""
let cur = D.faces[0].id;
const tabs = document.getElementById('tabs');
D.faces.forEach(f => { const b = document.createElement('button'); b.className = 'tab'; b.style.setProperty('--c', f.color);
  b.innerHTML = `<span class="dot"></span>${f.id} · ${f.area}${f.in_plan ? ' ⭐' : ''}`; b.dataset.id = f.id;
  b.onclick = () => { cur = f.id; draw(); }; tabs.appendChild(b); });

function hourly(f) {
  const W = 560, H = 170, P = { l: 6, r: 6, t: 14, b: 22 };
  const mx = Math.max(...f.hourly), x = h => P.l + h / 23 * (W - P.l - P.r), y = v => H - P.b - v / mx * (H - P.t - P.b);
  const pts = f.hourly.map((v, h) => `${x(h).toFixed(1)},${y(v).toFixed(1)}`);
  const area = `M${x(0)},${H - P.b} L${pts.join(' L')} L${x(23)},${H - P.b} Z`;
  const bands = [[7, 10], [17, 20]].map(([a, b]) => `<rect x="${x(a)}" y="${P.t - 8}" width="${x(b) - x(a)}" height="${H - P.b - P.t + 8}" rx="6" fill="color-mix(in srgb, ${f.color} 9%, white)"/>
     <text x="${(x(a) + x(b)) / 2}" y="${P.t - 12}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#8a889c">${a === 7 ? 'morning rush' : 'evening rush'}</text>`).join('');
  const ticks = [0, 6, 12, 18, 23].map(h => `<text x="${x(h)}" y="${H - 5}" text-anchor="middle" font-size="10.5" fill="#8a889c">${h === 0 ? '12am' : h === 12 ? '12pm' : h < 12 ? h + 'am' : (h - 12) + 'pm'}</text>`).join('');
  return `<div class="chartwrap"><svg viewBox="0 0 ${W} ${H + 8}" id="hsvg">${bands}
    <line x1="${P.l}" x2="${W - P.r}" y1="${H - P.b}" y2="${H - P.b}" stroke="#c3c2b7"/>
    <path d="${area}" fill="${f.color}" opacity=".16"/>
    <path d="M${pts.join(' L')}" fill="none" stroke="${f.color}" stroke-width="2.2" stroke-linejoin="round" id="hline"/>
    <line id="hx" y1="${P.t}" y2="${H - P.b}" stroke="#8a889c" stroke-dasharray="3 3" opacity="0"/>
    <circle id="hdot" r="4.5" fill="${f.color}" stroke="#fff" stroke-width="2" opacity="0"/>${ticks}
    <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" id="hhit"/></svg><div class="tip" id="htip"></div></div>`;
}
function draw() {
  const f = D.faces.find(x => x.id === cur);
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b.dataset.id === cur));
  const v = document.getElementById('view'); v.style.setProperty('--c', f.color);
  const hot = Object.entries(f.age).sort((a, b) => b[1] - a[1]).slice(0, 2).map(a => a[0]);
  v.innerHTML = `
  <div class="persona card fade"><div class="avatar">${f.avatar}</div><div><h3>${f.headline}</h3><p>${f.blurb}</p></div></div>
  <div class="stats">${f.stats.map((s, i) => `<div class="st card lift fade" style="animation-delay:${.05 + i * .06}s"><div class="e">${s[0]}</div><div class="n">${s[1]}</div><div class="l">${s[2]}</div></div>`).join('')}</div>
  <div class="two">
    <div class="panel card fade" style="animation-delay:.2s"><h4>When they drive past</h4><div class="sub">Views per hour on a typical weekday. Hover the curve.</div>${hourly(f)}</div>
    <div class="panel card fade" style="animation-delay:.26s"><h4>Who they are</h4><div class="sub">Age and gender of people around the board</div>
      <div class="ages">${Object.entries(f.age).map(([k, p]) => `<div class="age ${hot.includes(k) ? 'hot' : ''}"><span>${k}</span><div class="t"><i data-w="${p * 100 / Math.max(...Object.values(f.age))}"></i></div><b>${Math.round(p * 100)}%</b></div>`).join('')}</div>
      <div class="gender"><i data-w="${f.male * 100}" style="background:#2a78d6"></i><i data-w="${(1 - f.male) * 100}" style="background:#e87ba4"></i></div>
      <div class="glbl"><span>👨 ${Math.round(f.male * 100)}% men</span><span>${Math.round((1 - f.male) * 100)}% women 👩</span></div></div>
  </div>
  <div class="sowhat card fade" style="animation-delay:.32s">${f.sowhat}</div>`;
  requestAnimationFrame(() => setTimeout(() => v.querySelectorAll('[data-w]').forEach(x => x.style.width = x.dataset.w + '%'), reduce ? 0 : 120));
  const svg = v.querySelector('#hsvg'), hit = v.querySelector('#hhit'), tip = v.querySelector('#htip');
  const W = 560, mx = Math.max(...f.hourly);
  hit.onmousemove = e => { const r = svg.getBoundingClientRect(), sx = (e.clientX - r.left) / r.width * W;
    const h = Math.max(0, Math.min(23, Math.round((sx - 6) / (W - 12) * 23))), xx = 6 + h / 23 * (W - 12), yy = 170 - 22 - f.hourly[h] / mx * (170 - 36);
    v.querySelector('#hx').setAttribute('x1', xx); v.querySelector('#hx').setAttribute('x2', xx); v.querySelector('#hx').setAttribute('opacity', 1);
    const d = v.querySelector('#hdot'); d.setAttribute('cx', xx); d.setAttribute('cy', yy); d.setAttribute('opacity', 1);
    tip.style.opacity = 1; tip.innerHTML = `<b>${String(h).padStart(2, '0')}:00</b> · ${fmtP(f.hourly[h])} views`;
    tip.style.left = Math.min(r.width - 120, xx / W * r.width + 10) + 'px'; tip.style.top = (yy / 178 * r.height - 34) + 'px'; };
  hit.onmouseleave = () => { tip.style.opacity = 0; v.querySelector('#hx').setAttribute('opacity', 0); v.querySelector('#hdot').setAttribute('opacity', 0); };
  if (!reduce) { const line = v.querySelector('#hline'), L = line.getTotalLength(); line.style.strokeDasharray = L; line.style.strokeDashoffset = L;
    line.getBoundingClientRect(); line.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)'; line.style.strokeDashoffset = 0; }
  fit();
}
draw();
"""


def audience_html(data: dict) -> str:
    return _doc(_AUD_CSS, _AUD_BODY, _AUD_JS, data)


# --------------------------------------------------------------------------- campaign health


_HEALTH_CSS = r"""
.top { display:grid; grid-template-columns:300px 1fr; gap:16px; }
@media (max-width:860px) { .top { grid-template-columns:1fr; } }
.gauge { padding:18px; text-align:center; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.gauge svg { width:190px; height:190px; }
.gauge .lbl { font-size:13px; color:var(--ink2); margin-top:4px; }
.gauge .pct { font-size:40px; font-weight:800; letter-spacing:-.03em; }
.faces { padding:8px 6px; }
.fr { display:grid; grid-template-columns:26px 1.4fr 1fr 1.2fr 120px; gap:12px; align-items:center; padding:11px 14px; border-radius:14px;
      transition:background .15s; }
.fr:hover { background:var(--soft); }
.fr + .fr { border-top:1px solid var(--line); }
@media (max-width:760px) { .fr { grid-template-columns:22px 1fr 1fr; } .fr .spark, .fr .nums { display:none; } }
.fr .dot { width:12px; height:12px; border-radius:50%; background:var(--c); margin:auto; }
.fr b { font-size:15px; }
.fr .nm { font-size:12px; color:var(--muted); }
.nums { font-size:12.5px; color:var(--ink2); }
.nums strong { font-size:16px; color:var(--ink); }
.spark svg { width:100%; height:38px; display:block; }
.ev { margin-top:16px; }
.ev h3 { font-size:15px; margin:0 0 10px; display:flex; align-items:center; gap:8px; }
.evs { display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:12px; }
.e { padding:14px 16px; display:grid; grid-template-columns:62px 1fr; gap:12px; }
.cal { border-radius:12px; overflow:hidden; border:1px solid var(--line); text-align:center; background:#fff; height:fit-content; }
.cal .m { background:var(--crit); color:#fff; font-size:10.5px; font-weight:800; padding:2px 0; letter-spacing:.08em; }
.cal .d { font-size:24px; font-weight:800; padding:2px 0 0; }
.cal .w { font-size:10.5px; color:var(--muted); padding-bottom:4px; }
.e h4 { margin:0; font-size:14px; }
.e p { margin:4px 0 0; font-size:12.5px; color:var(--ink2); line-height:1.45; }
.e .row { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.empty { padding:18px; font-size:13.5px; color:var(--ink2); }
.foot { margin-top:12px; font-size:12px; color:var(--muted); line-height:1.5; }
"""

_HEALTH_BODY = r"""
<div class="top">
  <div class="gauge card fade"><div style="position:relative">
    <svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="80" fill="none" stroke="#ecebf3" stroke-width="16"/>
      <circle id="arc" cx="100" cy="100" r="80" fill="none" stroke-width="16" stroke-linecap="round" transform="rotate(-90 100 100)"
        stroke-dasharray="502.65" stroke-dashoffset="502.65" style="transition:stroke-dashoffset 1.3s cubic-bezier(.2,.8,.2,1)"/></svg>
    <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center">
      <div class="pct" id="pct">0%</div><div class="lbl">of planned views</div></div></div>
    <div style="margin-top:8px" id="status"></div><div class="lbl" id="gsub" style="margin-top:8px"></div></div>
  <div class="faces card fade" style="animation-delay:.08s" id="faces"></div>
</div>
<div class="ev"><h3>🚧 Things on the road that change the forecast</h3><div class="evs" id="evs"></div></div>
<div class="foot" id="foot"></div>
"""

_HEALTH_JS = r"""
function stat(p) { return p >= D.ok ? ['✅ On track', 'good', '#0ca30c'] : p >= D.watch ? ['👀 Keep an eye on it', 'warn', '#fab219'] : ['🔴 Behind plan', 'crit', '#d03b3b']; }
const s = stat(D.overall);
const arc = document.getElementById('arc'); arc.setAttribute('stroke', s[2]);
setTimeout(() => arc.style.strokeDashoffset = 502.65 * (1 - Math.min(1, D.overall)), reduce ? 0 : 150);
tween(document.getElementById('pct'), D.overall * 100, x => Math.round(x) + '%', 1200);
document.getElementById('status').innerHTML = `<span class="chip ${s[1]}">${s[0]}</span> <span class="chip warn" title="No media-owner play logs or live traffic counts are connected yet">🧪 Simulated</span>`;
document.getElementById('gsub').innerHTML = `${fmtP(D.actual)} delivered vs ${fmtP(D.planned)} planned`;
const fe = document.getElementById('faces');
D.faces.forEach((f, i) => {
  const st = stat(f.index), W = 120, H = 38, n = f.weeks.length;
  const lo = Math.min(.8, ...f.weeks), hi = Math.max(1.1, ...f.weeks), y = v => H - 4 - (v - lo) / (hi - lo) * (H - 8), x = k => 4 + k / Math.max(1, n - 1) * (W - 8);
  const d = f.weeks.map((v, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const r = document.createElement('div'); r.className = 'fr fade'; r.style.setProperty('--c', f.color); r.style.animationDelay = (.12 + i * .06) + 's';
  r.innerHTML = `<span class="dot"></span><div><b>${f.id}</b>${f.in_plan ? ' ⭐' : ''} <span class="nm">${f.area}${f.in_plan ? '' : ' · not in our pick'}</span><div><span class="chip ${st[1]}" style="margin-top:4px">${st[0]}</span></div></div>
    <div class="nums"><strong>${Math.round(f.index * 100)}%</strong> delivered<br>${fmtP(f.actual)} of ${fmtP(f.planned)}</div>
    <div class="nums">${f.news ? `News effect <strong>${f.news > 0 ? '+' : ''}${(f.news * 100).toFixed(1)}%</strong><br>${fmtP(Math.abs(f.news_views))} views ${f.news < 0 ? 'lost' : 'gained'}` : 'No road events<br>in the window'}</div>
    <div class="spark" title="Weekly delivery vs plan (dotted line = 100%)"><svg viewBox="0 0 ${W} ${H}"><line x1="0" x2="${W}" y1="${y(1)}" y2="${y(1)}" stroke="#c3c2b7" stroke-dasharray="3 3"/>
      <path d="${d}" fill="none" stroke="${f.color}" stroke-width="2" stroke-linejoin="round"/>
      ${f.weeks.map((v, k) => `<circle cx="${x(k)}" cy="${y(v)}" r="3" fill="${v < D.watch ? '#d03b3b' : f.color}" stroke="#fff" stroke-width="1.5"><title>Week ${k + 1}: ${Math.round(v * 100)}%</title></circle>`).join('')}</svg></div>`;
  fe.appendChild(r);
});
const ev = document.getElementById('evs');
if (!D.events.length) ev.innerHTML = '<div class="empty card">🌤️ No closures, roadworks or big events are expected near our billboards in the campaign window.</div>';
D.events.forEach((e, i) => {
  const c = document.createElement('div'); c.className = 'e card lift fade'; c.style.animationDelay = (.2 + i * .06) + 's';
  c.innerHTML = `<div class="cal"><div class="m">${e.mon}</div><div class="d">${e.day}</div><div class="w">${e.wd}</div></div>
    <div><h4>${e.title}</h4><p>${e.text}</p><div class="row">${e.chips.map(t => `<span class="chip ${t[1] || ''}">${t[0]}</span>`).join('')}</div></div>`;
  ev.appendChild(c);
});
document.getElementById('foot').innerHTML = D.foot;
fit();
"""


def health_html(data: dict) -> str:
    return _doc(_HEALTH_CSS, _HEALTH_BODY, _HEALTH_JS, data)
