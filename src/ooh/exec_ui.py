"""HTML blocks for the executive pages of the dashboard (white theme, animated, self-contained).

Each function takes plain data (dicts and lists built by the app from ``Results``) and returns one
HTML document for ``streamlit.components.v1.html``. All interaction (toggles, sorting, the
number-of-boards slider) runs in the browser, so it responds instantly without a Streamlit rerun. The numbers
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
.dots { display:inline-flex; gap:3px; vertical-align:middle; margin:0 8px 0 3px; }
.dots i { width:7px; height:7px; border-radius:50%; background:var(--line); }
.dots i.on { background:var(--accent); }
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
function dots(n, of) { of = of || 5; let h = '<span class="dots">';
  for (let k = 0; k < of; k++) h += `<i class="${k < n ? 'on' : ''}"></i>`; return h + '</span>'; }
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
    return ("<div class='ooh-head'>" + (f"<div class='ooh-eyebrow'>{eyebrow}</div>" if eyebrow else "")
            + f"<h1 class='ooh-title'>{title}</h1>" + (f"<p class='ooh-sub'>{subtitle}</p>" if subtitle else "")
            + "</div>")


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
.face.focus::before { content:"📍"; position:absolute; top:-10px; left:10px; font-size:14px; }
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
    <div class="bigrow"><div class="big" id="reach">0</div><div class="bigsub" id="bigsub"></div></div>
    <div class="range" id="range"></div>
    <div class="stats">
      <div class="stat"><div class="k">Everyone passing</div><div class="v" id="all">–</div><div class="s">people a month, all audiences</div></div>
      <div class="stat"><div class="k">Billboards</div><div class="v" id="nb">–</div><div class="s" id="nbs"></div></div>
      <div class="stat"><div class="k">Counted once</div><div class="v" id="dup">–</div><div class="s">repeat drivers not double-counted</div></div>
    </div>
    <div class="bud"><div class="budtrack"><div class="budfill" id="fill"></div></div>
      <div class="budlbl"><span id="budl"></span><span id="budr"></span></div></div>
    <div class="msg" id="msg"></div>
  </section>
  <section class="builder card fade" style="animation-delay:.08s">
    <div class="bhead"><div><b>Try your own mix</b><div class="hint">Tap a billboard to add or drop it</div></div>
      <button class="reset" id="reset">↺ Back to our pick</button></div>
    <div class="faces" id="faces"></div>
    <div class="slider"><div class="srow"><span>Number of boards</span><b id="bv"></b></div>
      <input type="range" id="boards" aria-label="Number of boards">
      <div class="hint" id="bhint"></div></div>
  </section>
</div>
"""

_DECISION_JS = r"""
const F = D.faces, byId = Object.fromEntries(F.map(f => [f.id, f]));
let k = D.boards, sel = new Set(D.picks[String(k)] || []), custom = false;
document.getElementById('trustname').textContent = D.trust[0];
document.getElementById('trustpop').textContent = D.trust[1];
document.getElementById('bigsub').innerHTML = `${D.aud_short}<br>reached every month`;
document.getElementById('bhint').textContent = `Move it and we re-pick the mix that reaches the most ${D.aud_short} for that many boards`;
const facesEl = document.getElementById('faces');
F.forEach((f, i) => {
  const b = document.createElement('button');
  b.className = 'face fade'; b.style.setProperty('--c', f.color); b.style.animationDelay = (0.12 + i * 0.06) + 's';
  b.dataset.id = f.id; if (f.focus) b.classList.add('focus');
  b.innerHTML = `<span class="ribbon">⭐ Our pick</span>
    <div class="ftop"><span class="dot"></span><b>${f.label}</b><span class="tick">✓</span></div>
    <div class="fname" title="${f.name}">${f.road} · ${f.type}</div>
    <div class="fnum">${fmtP(f.rel)} <small>${D.aud_short} / month</small></div>
    <div class="fsub"><span title="Value: ${D.aud_short} reached for the board's price level, best billboard = 5 dots (a rating, no prices used)">Value ${dots(f.value_dots)}</span>
      <span title="Our rating of price vs the other boards, no prices used">Price level ${dots(f.price_dots, 4)}</span></div>`;
  b.onclick = () => { sel.has(f.id) ? sel.delete(f.id) : sel.add(f.id); custom = true; render(); };
  facesEl.appendChild(b);
});
const slider = document.getElementById('boards');
slider.min = 1; slider.max = D.n_max; slider.step = 1; slider.value = k;
slider.oninput = () => { k = +slider.value; sel = new Set(D.picks[String(k)] || []); custom = false; render(); };
document.getElementById('reset').onclick = () => { sel = new Set(D.picks[String(k)] || []); custom = false; render(); };

function key(s) { return [...s].sort().join(','); }
function list(xs) { return xs.length <= 1 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1]; }
function names(ids) { return list(ids.map(i => byId[i].label)); }
function relOf(ids) { return ids.length ? D.subsets[key(new Set(ids))].rel : 0; }
function boardsWord(n) { return n === 1 ? '1 board' : `${n} boards`; }
function render() {
  const pickIds = D.picks[String(k)] || [], pickSet = new Set(pickIds);
  const ids = F.map(f => f.id).filter(i => sel.has(i));
  const order = pickIds.filter(i => sel.has(i)).concat(ids.filter(i => !pickSet.has(i)));
  const sub = ids.length ? D.subsets[key(sel)] : { rel: 0, all: 0 };
  const rel = sub.rel;
  const naive = ids.reduce((a, i) => a + byId[i].rel, 0);
  const lo = ids.reduce((a, i) => a + byId[i].rel_lo, 0), hi = ids.reduce((a, i) => a + byId[i].rel_hi, 0);
  const isPick = key(sel) === key(pickSet);

  document.querySelectorAll('.face').forEach(b => {
    b.classList.toggle('on', sel.has(b.dataset.id)); b.classList.toggle('pick', pickSet.has(b.dataset.id));
    b.setAttribute('aria-pressed', sel.has(b.dataset.id)); });
  document.getElementById('mode').textContent = isPick ? '🎯 Our recommendation' : '✏️ Your plan';
  document.getElementById('headline').innerHTML = ids.length
    ? `${order.length === F.length ? 'Book all four: ' : 'Book '}${list(order.map(i => `<span class="fc"><i style="background:${byId[i].color}"></i>${byId[i].label}</span>`))}`
    : 'No billboards picked yet';
  tween(document.getElementById('reach'), rel, fmtP);
  document.getElementById('range').textContent = ids.length
    ? `Likely between ${fmtP(rel * lo / naive)} and ${fmtP(rel * hi / naive)}, depending on how often people repeat the trip`
    : 'Tap a billboard on the right to start';
  tween(document.getElementById('all'), sub.all, fmtP);
  document.getElementById('nb').textContent = `${ids.length} of ${F.length}`;
  document.getElementById('nbs').textContent = ids.length ? `${ids.filter(i => byId[i].type === 'Digital').length} digital, ${ids.filter(i => byId[i].type !== 'Digital').length} static` : '';
  tween(document.getElementById('dup'), naive - rel, fmtP);

  const fill = document.getElementById('fill');
  fill.style.width = Math.min(100, ids.length / D.n_max * 100) + '%'; fill.classList.toggle('over', ids.length > k);
  document.getElementById('budl').textContent = `${ids.length} of ${D.n_max} boards picked`;
  document.getElementById('budr').textContent = k === D.boards ? `The brief books ${boardsWord(D.boards)}` : `Trying ${boardsWord(k)} (brief: ${D.boards})`;
  document.getElementById('bv').textContent = k === D.boards ? `${k} · as in the brief` : `${k}`;
  slider.style.setProperty('--p', (D.n_max > 1 ? (k - 1) / (D.n_max - 1) * 100 : 100) + '%');

  const msg = document.getElementById('msg'); msg.className = 'msg';
  const pickRel = relOf(pickIds);
  const A = D.aud_short;
  if (!ids.length) { msg.textContent = 'Pick at least one billboard to see who we reach.'; }
  else if (isPick) {
    msg.className = 'msg good';
    const next = D.picks[String(k + 1)];
    msg.innerHTML = `✅ The most ${A} for ${boardsWord(k)}.` + (k < D.n_max && next
      ? ` One more board (${names(next.filter(i => !pickSet.has(i))) || names(next)}) would add ${fmtP(Math.max(0, relOf(next) - pickRel))} ${A}.`
      : ' Every board is in the plan.');
  } else if (ids.length !== k) {
    const best = D.picks[String(ids.length)] || [], bestRel = relOf(best);
    msg.innerHTML = `ℹ️ You picked ${boardsWord(ids.length)}; the slider is set to ${k}.` +
      (rel < bestRel - 1 ? ` For ${boardsWord(ids.length)}, ${names(best)} reaches <b>${fmtP(bestRel - rel)} more ${A}</b>.`
                         : ` This is the best mix for ${boardsWord(ids.length)}.`);
  } else if (rel < pickRel - 1) {
    msg.innerHTML = `💡 Our pick for ${boardsWord(k)} (${names(pickIds)}) reaches <b>${fmtP(pickRel - rel)} more ${A}</b> than this mix.`;
  } else {
    msg.className = 'msg good';
    msg.innerHTML = `🙌 This mix reaches as many ${A} as our pick for ${boardsWord(k)}.`;
  }
  fit();
}
render();
"""


def decision_html(data: dict) -> str:
    return _doc(_DECISION_CSS, _DECISION_BODY, _DECISION_JS, data)


# --------------------------------------------------------------------------- decision: insight tiles


_INSIGHTS_CSS = r"""
.grid { display:grid; grid-template-columns:repeat(var(--n, 3), 1fr); gap:16px; }
@media (max-width:1150px) { .grid { grid-template-columns:repeat(2, 1fr); } }
@media (max-width:640px) { .grid { grid-template-columns:1fr; } }
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
const g = document.getElementById('grid'); g.style.setProperty('--n', D.tiles.length);
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
.row { display:grid; grid-template-columns:54px 1.5fr .85fr 1.5fr 1fr .8fr; gap:16px; align-items:center; padding:14px 18px; position:relative; }
.row.focus { border-color:#bdb3f5; box-shadow:0 0 0 3px #efedfc, var(--shadow); }
.row.focus::after { content:"📍 Your focus"; position:absolute; top:-9px; right:16px; font-size:10.5px; font-weight:800; color:var(--accent); background:#fff; border:1px solid #dcd7fb; border-radius:999px; padding:1px 8px; }
@media (max-width:860px) { .row { grid-template-columns:44px 1fr 1fr; } .row .reachcol, .row .cppcol, .row .pricecol { grid-column:2 / span 2; } }
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
.cppbar i { display:block; height:100%; width:0; background:linear-gradient(90deg, #8b7cf0, #6250d6);
            border-radius:999px; transition:width .9s cubic-bezier(.2,.8,.2,1); }
.note { margin-top:14px; font-size:12.5px; color:var(--muted); line-height:1.5; }
"""

_LEAGUE_BODY = r"""
<div class="bar"><div class="seg" id="seg">
  <button data-k="value" class="on">💎 Best value</button><button data-k="reach" id="reachbtn">🎯 Biggest target audience</button><button data-k="price" title="Our 1-4 price-level rating, no prices used">🏷️ Lowest price level</button>
</div><span class="chip trust" tabindex="0">◔ <span id="tn"></span><span class="pop" id="tp"></span></span></div>
<div class="list" id="list"></div>
<div class="note" id="note"></div>
"""

_LEAGUE_JS = r"""
document.getElementById('tn').textContent = D.trust[0]; document.getElementById('tp').textContent = D.trust[1];
document.getElementById('note').innerHTML = D.note;
document.getElementById('reachbtn').textContent = `🎯 Most ${D.aud_short}`;
const L = document.getElementById('list'), maxHi = Math.max(...D.rows.map(r => r.rel_hi));
const els = {};
D.rows.forEach(r => {
  const d = document.createElement('div'); d.className = 'row card lift'; d.style.setProperty('--c', r.color);
  d.dataset.id = r.id; if (r.focus) d.classList.add('focus');
  d.innerHTML = `<div class="medal"></div>
    <div><div class="id"><span class="dot"></span><b>${r.label}</b></div><div class="nm">${r.road} · ${r.type_note}</div>
      <div class="tags">${r.tags.map(t => `<span class="chip ${t[1] || ''}">${t[0]}</span>`).join('')}</div></div>
    <div><div class="k">Everyone passing</div><div class="v">${fmtP(r.unique)}</div><div class="rtxt">people a month</div></div>
    <div class="reachcol"><div class="k">${D.aud_cap} / month</div><div class="v">${fmtP(r.rel)}</div>
      <div class="track"><div class="rng" style="left:${r.rel_lo / maxHi * 100}%;width:${(r.rel_hi - r.rel_lo) / maxHi * 100}%"></div><div class="fillb" data-w="${r.rel / maxHi * 100}"></div></div>
      <div class="rtxt">likely ${fmtP(r.rel_lo)} – ${fmtP(r.rel_hi)}</div></div>
    <div class="cppcol"><div class="k" title="Target audience for the price level of the board (a rating, no prices used)">Value</div><div class="v">${r.value}<small> / 100</small></div>
      <div class="cppbar"><i data-w="${r.value}"></i></div><div class="rtxt">${r.value_note}</div></div>
    <div class="pricecol"><div class="k" title="Our rating of price vs the other boards, no prices used">Price level</div><div class="v" style="font-size:15px;margin-top:6px">${dots(r.price_dots, 4)}</div><div class="rtxt">${r.price_note}</div></div>`;
  L.appendChild(d); els[r.id] = d;
});
const medals = ['🥇', '🥈', '🥉', '🎗️'];
function sortBy(k) {
  const before = Object.fromEntries(Object.entries(els).map(([id, e]) => [id, e.getBoundingClientRect().top]));
  const rows = [...D.rows].sort((a, b) => k === 'value' ? b.value - a.value : k === 'reach' ? b.rel - a.rel : a.price_rank - b.price_rank);
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
.sec { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin:20px 2px 2px; }
.sec span { font-size:15px; font-weight:800; }
.sec em { font-style:normal; font-size:12.5px; color:var(--muted); }
.sec.target span { color:var(--accent); }
.st.tgt { background:linear-gradient(160deg, #f6f4ff, #fff); border-color:#e4e0fb; }
.st.tgt .n { color:var(--accent); }
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
let cur = D.focus || D.faces[0].id;
const tabs = document.getElementById('tabs');
D.faces.forEach(f => { const b = document.createElement('button'); b.className = 'tab'; b.style.setProperty('--c', f.color);
  b.innerHTML = `<span class="dot"></span>${f.label}${f.in_plan ? ' ⭐' : ''}`; b.dataset.id = f.id;
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
  <div class="sec"><span>👥 Everyone who passes</span><em>general audience, useful for any brand</em></div>
  <div class="stats">${f.general.map((s, i) => `<div class="st card lift fade" style="animation-delay:${.05 + i * .06}s"><div class="e">${s[0]}</div><div class="n">${s[1]}</div><div class="l">${s[2]}</div></div>`).join('')}</div>
  <div class="two">
    <div class="panel card fade" style="animation-delay:.2s"><h4>When they drive past</h4><div class="sub">Views per hour on a typical weekday. Hover the curve.</div>${hourly(f)}</div>
    <div class="panel card fade" style="animation-delay:.26s"><h4>Who they are</h4><div class="sub">Age and gender of people around the board</div>
      <div class="ages">${Object.entries(f.age).map(([k, p]) => `<div class="age ${hot.includes(k) ? 'hot' : ''}"><span>${k}</span><div class="t"><i data-w="${p * 100 / Math.max(...Object.values(f.age))}"></i></div><b>${Math.round(p * 100)}%</b></div>`).join('')}</div>
      <div class="gender"><i data-w="${f.male * 100}" style="background:#2a78d6"></i><i data-w="${(1 - f.male) * 100}" style="background:#e87ba4"></i></div>
      <div class="glbl"><span>👨 ${Math.round(f.male * 100)}% men</span><span>${Math.round((1 - f.male) * 100)}% women 👩</span></div></div>
  </div>
  <div class="sec target"><span>${D.emoji} Our campaign audience: ${D.audience}</span><em>${D.campaign}</em></div>
  <div class="stats">${f.target.map((s, i) => `<div class="st card lift fade tgt" style="animation-delay:${.3 + i * .06}s"><div class="e">${s[0]}</div><div class="n">${s[1]}</div><div class="l">${s[2]}</div></div>`).join('')}</div>
  <div class="sowhat card fade" style="animation-delay:.4s">${f.sowhat}</div>`;
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
  r.innerHTML = `<span class="dot"></span><div><b>${f.label}</b>${f.in_plan ? ' ⭐' : ''} <span class="nm">${f.in_plan ? f.road : 'not in our pick'}</span><div><span class="chip ${st[1]}" style="margin-top:4px">${st[0]}</span></div></div>
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


# --------------------------------------------------------------------------- what's on nearby (people facts)


_PULSE_CSS = _AUD_CSS + r"""
.phero { padding:20px 22px; background:radial-gradient(120% 160% at 0% 0%, #f1eeff 0%, #ffffff 60%), #fff; }
.phero .eb { font-size:12.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--accent);
             display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; align-items:center; }
.phero .eb .chip { text-transform:none; letter-spacing:0; }
.phero h2 { margin:8px 0 4px; font-size:23px; line-height:1.25; letter-spacing:-.01em; }
.phero p { margin:0; color:var(--ink2); font-size:13.5px; line-height:1.5; }
.kpis { display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-top:14px; }
@media (max-width:820px) { .kpis { grid-template-columns:1fr; } }
.kpi { padding:12px 14px; background:#fff; }
.kpi .n { font-size:26px; font-weight:800; letter-spacing:-.02em; }
.kpi .l { font-size:12.5px; color:var(--ink2); margin-top:2px; line-height:1.35; }
.kpi.tgt .n { color:var(--accent); }
.verdict { margin-top:14px; padding:12px 16px; border-radius:14px; font-size:13.5px; line-height:1.5; color:var(--ink2);
           background:#f3fbf3; border:1px solid #cdeccd; }
.verdict.change { background:var(--accent-soft); border-color:#dcd7fb; }
.verdict b { color:var(--ink); }
.cal { padding:16px 18px; margin-top:14px; position:relative; }
.cal h4 { margin:0; font-size:14.5px; } .cal .sub { font-size:12px; color:var(--muted); margin:2px 0 10px; }
.crow { display:grid; grid-template-columns:118px 1fr; align-items:center; gap:8px; height:34px; }
.crow .nm { font-size:12.5px; font-weight:700; display:flex; align-items:center; gap:6px; white-space:nowrap; overflow:hidden; }
.crow .nm i { width:9px; height:9px; border-radius:50%; flex:none; }
.track { position:relative; height:100%; border-bottom:1px dashed var(--line); }
.track .wk { position:absolute; top:4px; bottom:4px; width:1px; background:var(--line); }
.bub { position:absolute; top:50%; border-radius:50%; transform:translate(-50%, -50%) scale(0); cursor:pointer;
       border:2px solid #fff; box-shadow:0 1px 3px rgba(29,27,46,.25); animation:popb .5s cubic-bezier(.2,.8,.2,1) forwards; }
.bub.car { outline:2.5px solid var(--accent); outline-offset:1px; }
.bub span { position:absolute; inset:0; display:grid; place-items:center; font-size:11px; }
@keyframes popb { to { transform:translate(-50%, -50%) scale(1); } }
.axis { display:grid; grid-template-columns:118px 1fr; gap:8px; margin-top:4px; }
.axis .ticks { position:relative; height:16px; font-size:11px; color:var(--muted); }
.axis .ticks span { position:absolute; transform:translateX(-50%); white-space:nowrap; }
.legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--ink2); margin-top:8px; }
.legend i { display:inline-block; width:11px; height:11px; border-radius:50%; background:#c9c6dc; vertical-align:-1px; margin-right:5px; }
.legend i.car { outline:2.5px solid var(--accent); outline-offset:1px; background:#fff; }
.ptip { position:absolute; z-index:30; pointer-events:none; background:#fff; border:1px solid var(--line); border-radius:12px;
        padding:9px 12px; font-size:12px; box-shadow:var(--shadow-up); opacity:0; transition:opacity .12s; max-width:300px; line-height:1.45; }
.ptip b { color:var(--ink); } .ptip q { display:block; color:var(--ink2); font-style:italic; margin-top:4px; }
.evs { display:flex; flex-direction:column; gap:10px; margin-top:10px; }
.ev { padding:12px 14px; display:grid; grid-template-columns:62px 1fr auto; gap:12px; align-items:center; }
@media (max-width:700px) { .ev { grid-template-columns:52px 1fr; } .ev .big { grid-column:2; text-align:left; } }
.date { text-align:center; border-radius:12px; background:var(--soft); border:1px solid var(--line); padding:6px 4px; }
.date b { display:block; font-size:19px; line-height:1; } .date span { font-size:11px; color:var(--muted); font-weight:700; text-transform:uppercase; }
.ev h5 { margin:0; font-size:14.5px; } .ev .meta { margin-top:5px; display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.ev .big { text-align:right; } .ev .big .n { font-size:21px; font-weight:800; letter-spacing:-.02em; }
.ev .big .l { font-size:11.5px; color:var(--ink2); }
.ev.car { border-color:#dcd7fb; background:linear-gradient(160deg, #f8f6ff, #fff); }
.ev.car .big .n { color:var(--accent); }
.empty { padding:14px 16px; font-size:13px; color:var(--muted); border:1.5px dashed var(--line); border-radius:14px; margin-top:10px; }
.facts { display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-top:10px; }
@media (max-width:820px) { .facts { grid-template-columns:1fr 1fr; } }
.fact { padding:13px 15px; display:flex; flex-direction:column; gap:3px; }
.fact .top { display:flex; justify-content:space-between; align-items:flex-start; gap:6px; }
.fact .e { font-size:19px; } .fact .n { font-size:22px; font-weight:800; letter-spacing:-.02em; }
.fact .u { font-size:12.5px; color:var(--ink2); } .fact .w { font-size:13px; font-weight:700; margin-top:2px; }
.fact .meta { display:flex; gap:5px; flex-wrap:wrap; margin-top:6px; }
a.src { color:var(--accent); font-size:12px; font-weight:600; text-decoration:none; }
a.src:hover { text-decoration:underline; }
.srcs { display:inline-flex; gap:8px; flex-wrap:wrap; }
.away { margin-top:20px; padding:14px 18px; }
.away h4 { margin:0; font-size:14.5px; } .away .sub { font-size:12px; color:var(--muted); margin:2px 0 8px; }
.away .row { display:flex; gap:8px; flex-wrap:wrap; }
"""

_PULSE_BODY = r"""
<div id="hero"></div>
<div class="cal card fade" id="cal" style="animation-delay:.08s"></div>
<div class="tabs" id="tabs" style="margin-top:18px"></div>
<div id="view"></div>
<div id="away"></div>
<div class="ptip" id="ptip"></div>
"""

_PULSE_JS = r"""
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl = u => /^https?:\/\//i.test(u || '') ? esc(u) : '#';
const PER = { year:' a year', month:' a month', week:' a week', day:' a day', hour:' an hour', event:'', total:'' };
const MEAS = { count:['counted', 'good'], expected:['expected', ''], capacity:['capacity, not a count', 'warn'] };
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const dt = s => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const dayIdx = s => Math.round((dt(s) - dt(D.start)) / 864e5);
const dlabel = (a, b) => { const x = dt(a), y = dt(b || a); const f = d => d.getUTCDate() + ' ' + MON[d.getUTCMonth()];
  return +x === +y ? f(x) : (x.getUTCMonth() === y.getUTCMonth() ? x.getUTCDate() + '–' + f(y) : f(x) + ' – ' + f(y)); };
function chips(f) { let h = '';
  if (f.measure && MEAS[f.measure]) h += `<span class="chip ${MEAS[f.measure][1]}">${MEAS[f.measure][0]}</span>`;
  if (f.year) h += `<span class="chip ${f.old ? 'warn' : ''}">${f.year} figure${f.old ? ' · old' : ''}</span>`;
  if (f.match) h += `<span class="chip accent">${D.emoji} ${esc(D.audience_short)}</span>`;
  if (f.sources_n > 1) h += `<span class="chip good">${f.sources_n} sources agree${f.range ? ' (' + f.range + ')' : ''}</span>`;
  return h; }
function srcs(list) { return '<span class="srcs">' + list.slice(0, 3).map(s =>
  `<a class="src trust" href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc((s.title || 'source').slice(0, 38))} ↗<span class="pop">“${esc(s.quote)}”</span></a>`).join('') + '</span>'; }

// ---- hero
(function hero() {
  const S = D.summary, el = document.getElementById('hero');
  const head = S.n_events === 0
    ? `No dated crowd events found next to our billboards in ${esc(D.window)}`
    : `${S.n_events} crowd event${S.n_events > 1 ? 's' : ''} next to our billboards in ${esc(D.window)}` +
      (S.n_car ? `, <span style="color:var(--accent)">${S.n_car} for ${esc(D.audience_short)}</span>` : '');
  const verdict = S.changed
    ? `<div class="verdict change">🔀 <b>Counting these crowds changes our pick:</b> ${esc(S.before)} → <b>${esc(S.after)}</b>. Worth a look on the Decision page.</div>`
    : `<div class="verdict">✅ <b>Doesn't change our pick.</b> ${S.extra > 0 ? `Everyday traffic past our billboards is about <b>${S.ratio}× bigger</b> than these crowds over the month.` : 'Our pick rests on everyday traffic.'} ${S.best ? `Use the news for <b>timing</b>: ${esc(S.best)}.` : ''}</div>`;
  el.innerHTML = `<div class="phero card fade"><div class="eb"><span>📣 What the news says · ${esc(D.window)}</span>
      <span class="chip accent trust" tabindex="0">Sourced numbers<span class="pop">Every number below is quoted from a news or official page (hover a source link to read it). Turning a crowd into people passing our board uses our assumption that ${D.pass_share}% of visitors pass a nearby billboard.</span></span></div>
    <h2>${head}</h2>
    <p>Big events bring extra people past a billboard for a day or two. Visitor and resident numbers show why a spot is busy every day.</p>
    <div class="kpis">
      <div class="kpi card"><div class="n" data-t="${S.extra}">0</div><div class="l">extra people passing our billboards on event days</div></div>
      <div class="kpi card tgt"><div class="n" data-t="${S.target}">0</div><div class="l">of them ${esc(D.audience_short)}</div></div>
      <div class="kpi card"><div class="n">${S.n_facts}</div><div class="l">sourced numbers about our locations</div></div>
    </div>${verdict}</div>`;
  el.querySelectorAll('[data-t]').forEach(n => tween(n, +n.dataset.t, x => (x > 0 ? '+' : '') + fmtP(x), 900));
})();

// ---- calendar strip
(function cal() {
  const el = document.getElementById('cal'), N = D.days;
  const all = D.faces.flatMap(f => f.events.map(e => e.extra));
  const mx = Math.max(1, ...all);
  const pos = i => ((i + .5) / N * 100).toFixed(2) + '%';
  let rows = D.faces.map(f => {
    const wk = [7, 14, 21, 28].filter(d => d < N).map(d => `<span class="wk" style="left:${(d / N * 100).toFixed(2)}%"></span>`).join('');
    const bubs = f.events.map((e, k) => { const a = Math.max(0, dayIdx(e.start)), b = Math.min(N - 1, dayIdx(e.end || e.start));
      const sz = 12 + 22 * Math.sqrt(e.extra / mx);
      return `<span class="bub ${e.match ? 'car' : ''}" data-f="${f.id}" data-k="${k}" style="left:${pos((a + b) / 2)};width:${sz}px;height:${sz}px;background:${f.color};animation-delay:${.2 + k * .08}s"></span>`; }).join('');
    return `<div class="crow"><div class="nm"><i style="background:${f.color}"></i>${esc(f.label)}${f.in_plan ? ' ⭐' : ''}</div><div class="track">${wk}${bubs}</div></div>`; }).join('');
  const ticks = [0, 7, 14, 21, 28].filter(d => d < N).map(d => { const x = new Date(+dt(D.start) + d * 864e5);
    return `<span style="left:${pos(d)}">${x.getUTCDate()} ${MON[x.getUTCMonth()]}</span>`; }).join('');
  el.innerHTML = `<h4>When the crowds come</h4><div class="sub">Each bubble is an event with a sourced attendance figure. Size = extra people passing our board. Hover for the source.</div>
    ${rows}<div class="axis"><span></span><div class="ticks">${ticks}</div></div>
    <div class="legend"><span><i></i>general crowd</span><span><i class="car"></i>${esc(D.audience_short)} crowd</span><span>⭐ in our current pick</span></div>`;
  const tip = document.getElementById('ptip');
  el.querySelectorAll('.bub').forEach(b => {
    b.onmouseenter = () => { const f = D.faces.find(x => x.id === b.dataset.f), e = f.events[+b.dataset.k];
      tip.innerHTML = `<b>${esc(e.what)}</b> · ${dlabel(e.start, e.end)}<br>${fmtP(e.visitors)} visitors (${MEAS[e.measure] ? MEAS[e.measure][0] : ''}) → <b>~${fmtP(e.extra)}</b> pass our ${esc(f.label)} board${e.match ? `, ~${fmtP(e.target)} ${esc(D.audience_short)}` : ''}<q>“${esc(e.sources[0].quote)}”</q><span class="muted">${esc(e.sources[0].title)}</span>`;
      const r = b.getBoundingClientRect(); tip.style.opacity = 1;
      tip.style.left = Math.max(4, Math.min(document.body.clientWidth - 310, r.left + window.scrollX - 140)) + 'px';
      tip.style.top = (r.bottom + window.scrollY + 8) + 'px'; };
    b.onmouseleave = () => tip.style.opacity = 0;
    b.onclick = () => { cur = b.dataset.f; draw(); document.getElementById('tabs').scrollIntoView({ behavior: reduce ? 'auto' : 'smooth' }); };
  });
})();

// ---- per location
let cur = D.focus || D.faces[0].id;
const tabs = document.getElementById('tabs');
D.faces.forEach(f => { const b = document.createElement('button'); b.className = 'tab'; b.style.setProperty('--c', f.color);
  b.innerHTML = `<span class="dot"></span>${esc(f.label)}${f.in_plan ? ' ⭐' : ''} <span class="muted" style="font-weight:600">${f.n_facts}</span>`; b.dataset.id = f.id;
  b.onclick = () => { cur = f.id; draw(); }; tabs.appendChild(b); });

function evRow(e, i, f) {
  const d = dt(e.start);
  return `<div class="ev card lift fade ${e.match ? 'car' : ''}" style="animation-delay:${.05 + i * .06}s">
    <div class="date"><span>${MON[d.getUTCMonth()]}</span><b>${d.getUTCDate()}</b>${e.end && e.end !== e.start ? `<span>to ${dt(e.end).getUTCDate()}</span>` : ''}</div>
    <div><h5>${e.icon} ${esc(e.what)}</h5><div class="muted" style="font-size:12.5px;margin-top:2px">${fmtP(e.visitors)} visitors during the campaign${e.note ? ' · ' + esc(e.note) : ''}</div>
      <div class="meta">${chips(e)} ${srcs(e.sources)}</div></div>
    <div class="big"><div class="n">+${fmtP(e.match ? e.target : e.extra)}</div><div class="l">${e.match ? esc(D.audience_short) + ' passing' : 'people passing'}<br>our board${e.capped ? ' (capped)' : ''}</div></div></div>`; }
function factCard(x, i) {
  return `<div class="fact card lift fade" style="animation-delay:${.05 + i * .05}s"><div class="top"><span class="e">${x.icon}</span></div>
    <div><span class="n">${fmtP(x.value)}</span> <span class="u">${esc(x.unit)}${PER[x.period] || ''}</span></div>
    <div class="w">${esc(x.what)}</div>${x.note ? `<div class="muted" style="font-size:12px">${esc(x.note)}</div>` : ''}
    <div class="meta">${chips(x)}</div><div style="margin-top:4px">${srcs(x.sources)}</div></div>`; }
function draw() {
  const f = D.faces.find(x => x.id === cur);
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b.dataset.id === cur));
  const v = document.getElementById('view'); v.style.setProperty('--c', f.color);
  const car = f.events.filter(e => e.match), gen = f.events.filter(e => !e.match);
  const laterCar = f.later.filter(x => x.match), laterGen = f.later.filter(x => !x.match);
  v.innerHTML = `
  <div class="sec target"><span>${D.emoji} Crowds of ${esc(D.audience_short)} near ${esc(f.label)}</span><em>${esc(D.window)}</em></div>
  ${car.length ? `<div class="evs">${car.map((e, i) => evRow(e, i, f)).join('')}</div>` : `<div class="empty">No ${esc(D.audience_short)} event with a published crowd figure near ${esc(f.label)} during ${esc(D.window)}.</div>`}
  ${laterCar.length ? `<div class="sec"><span>📅 ${esc(D.audience_short)} events here on other dates</span><em>not in this campaign's window, or this year's dates not announced yet</em></div><div class="facts">${laterCar.map(factCard).join('')}</div>` : ''}
  <div class="sec"><span>👥 General crowds near ${esc(f.label)}</span><em>${esc(D.window)}</em></div>
  ${gen.length ? `<div class="evs">${gen.map((e, i) => evRow(e, i, f)).join('')}</div>` : `<div class="empty">No other dated crowd event with a published figure during ${esc(D.window)}.</div>`}
  ${laterGen.length ? `<div class="sec"><span>📅 Other big crowds here</span><em>other dates</em></div><div class="facts">${laterGen.map(factCard).join('')}</div>` : ''}
  <div class="sec"><span>📌 Why ${esc(f.label)} is busy every day</span><em>visitors, residents, workers, metro riders and traffic, as published</em></div>
  ${f.context.length ? `<div class="facts">${f.context.map(factCard).join('')}</div>` : `<div class="empty">No published visitor, resident or ridership numbers found yet.</div>`}`;
  fit();
}
draw();

// ---- elsewhere
(function away() {
  if (!D.away.length) return;
  document.getElementById('away').innerHTML = `<div class="away card fade"><h4>${D.emoji} ${esc(D.audience_short)} crowds elsewhere in Dubai</h4>
    <div class="sub">None of our billboards is nearby. Useful for activation or for choosing future sites.</div>
    <div class="row">${D.away.map(x => `<span class="chip ${x.in_window ? 'accent' : ''} trust" tabindex="0">${x.icon} ${esc(x.what)} · ${fmtP(x.value)}${x.when ? ' · ' + esc(x.when) : ''}<span class="pop">“${esc(x.quote)}” (${esc(x.title)})</span></span>`).join('')}</div></div>`;
})();
"""


def pulse_html(data: dict) -> str:
    return _doc(_PULSE_CSS, _PULSE_BODY, _PULSE_JS, data)


# --------------------------------------------------------------------------- explore a location (knowledge layer)

_ESC_JS = r"""
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl = u => /^https?:\/\//i.test(u || '') ? esc(u) : '';
const TRUSTW = { VERIFIED:['Solid','good'], ESTIMATE:['Good estimate',''], ASSUMPTION:['Our assumption','warn'],
                 SAMPLE:['Placeholder','warn'], CONCEPT:['Idea stage',''] };
"""

_EXPLORE_CSS = r"""
.idc { padding:20px 22px; display:grid; grid-template-columns:auto 1fr auto; gap:18px; align-items:center;
       background:radial-gradient(120% 160% at 0% 0%, color-mix(in srgb, var(--c) 14%, white), #fff 60%); }
@media (max-width:760px) { .idc { grid-template-columns:auto 1fr; } .idc .rank { grid-column:1 / -1; } }
.pinb { width:62px; height:62px; border-radius:20px; background:var(--c); display:grid; place-items:center; font-size:30px;
        box-shadow:0 8px 22px color-mix(in srgb, var(--c) 40%, transparent); animation:pop .5s cubic-bezier(.2,.8,.2,1) both; }
.idc h2 { margin:0; font-size:24px; letter-spacing:-.01em; } .idc p { margin:4px 0 0; color:var(--ink2); font-size:13.5px; }
.idc .chips { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.rank { text-align:center; padding:10px 16px; border-radius:16px; background:#fff; border:1px solid var(--line); }
.rank b { display:block; font-size:30px; letter-spacing:-.02em; color:var(--accent); } .rank span { font-size:12px; color:var(--ink2); }
.eng { display:grid; grid-template-columns:repeat(6, 1fr); gap:10px; margin-top:14px; }
@media (max-width:980px) { .eng { grid-template-columns:repeat(3, 1fr); } }
@media (max-width:560px) { .eng { grid-template-columns:repeat(2, 1fr); } }
.eg { padding:12px 14px; } .eg .e { font-size:18px; } .eg .n { font-size:21px; font-weight:800; letter-spacing:-.02em; margin-top:2px; }
.eg .l { font-size:12px; color:var(--ink2); line-height:1.3; } .eg.tgt .n { color:var(--accent); }
.kl { margin-top:16px; padding:16px 18px; }
.kl .head { display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }
.kl h3 { margin:0; font-size:16.5px; } .kl .sub { font-size:12.5px; color:var(--ink2); margin-top:3px; }
.funnel { display:flex; align-items:center; gap:10px; font-size:13px; color:var(--ink2); }
.funnel b { font-size:22px; color:var(--ink); letter-spacing:-.02em; } .funnel b.u { color:var(--accent); }
.funnel .arr { color:var(--muted); font-size:18px; }
.fchips { display:flex; gap:6px; flex-wrap:wrap; margin:14px 0 4px; }
.fchip { font:inherit; font-size:12.5px; font-weight:700; border:1.5px solid var(--line); background:#fff; color:var(--ink2);
         border-radius:999px; padding:5px 11px; cursor:pointer; transition:all .15s; }
.fchip.on { border-color:var(--accent); background:var(--accent-soft); color:var(--accent); }
.fchip i { font-style:normal; opacity:.6; margin-left:4px; }
.kgrid { display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; margin-top:10px; }
@media (max-width:980px) { .kgrid { grid-template-columns:repeat(2, 1fr); } }
@media (max-width:560px) { .kgrid { grid-template-columns:1fr; } }
.kf { padding:12px 14px; display:flex; flex-direction:column; gap:4px; position:relative; }
.kf .tp { font-size:11.5px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.kf .v { font-size:18px; font-weight:800; letter-spacing:-.01em; line-height:1.25; }
.kf .t { font-size:13px; color:var(--ink2); }
.kf .why { font-size:12px; color:var(--accent); font-weight:600; }
.kf .meta { display:flex; gap:5px; flex-wrap:wrap; margin-top:4px; align-items:center; }
.kf .rel { position:absolute; top:12px; right:12px; width:34px; height:5px; border-radius:999px; background:var(--line); overflow:hidden; }
.kf .rel i { display:block; height:100%; background:var(--accent); }
.kf.off { opacity:.62; } .kf.off .why { color:var(--muted); }
.more { margin-top:12px; font:inherit; font-size:13px; font-weight:700; color:var(--accent); background:none; border:none; cursor:pointer; padding:4px 0; }
a.src { color:var(--accent); font-size:12px; font-weight:600; text-decoration:none; } a.src:hover { text-decoration:underline; }
"""

_EXPLORE_BODY = r"""<div id="id"></div><div class="eng" id="eng"></div><div class="kl card fade" id="kl" style="animation-delay:.15s"></div>"""

_EXPLORE_JS = _ESC_JS + r"""
const L = D.loc, C = D.campaign;
document.body.style.setProperty('--c', L.color);
document.getElementById('id').innerHTML = `<div class="idc card fade"><div class="pinb">📍</div>
  <div><h2>${esc(L.label)} <span class="muted" style="font-size:15px;font-weight:600">· ${esc(L.road)}</span></h2>
  <p>${esc(L.format)} · ${esc(L.size)} · ${esc(L.price_word)}</p>
  <div class="chips">${L.in_plan ? '<span class="chip accent">⭐ In our plan</span>' : '<span class="chip">Not in our plan</span>'}
  ${(L.tags || []).map(t => `<span class="chip">${esc(t)}</span>`).join('')}</div></div>
  <div class="rank"><b>#${L.rank}</b><span>of ${L.n} for the<br>${esc(C.emoji)} ${esc(C.title)}</span></div></div>`;
document.getElementById('eng').innerHTML = D.engage.map((e, i) =>
  `<div class="eg card lift fade ${e[3] ? 'tgt' : ''}" style="animation-delay:${.05 + i * .05}s"><div class="e">${e[0]}</div><div class="n">${esc(e[1])}</div><div class="l">${esc(e[2])}</div></div>`).join('');

let topic = 'all', showAll = false;
function card(f, i) {
  const tw = TRUSTW[f.trust] || [f.trust, ''];
  const link = safeUrl(f.url) ? `<a class="src trust" href="${safeUrl(f.url)}" target="_blank" rel="noopener">source ↗${f.quote ? `<span class="pop">“${esc(f.quote)}”</span>` : ''}</a>` : '';
  return `<div class="kf card lift fade ${f.used ? '' : 'off'}" style="animation-delay:${Math.min(.4, .03 * i)}s">
    <div class="rel" title="relevance ${Math.round(f.score * 100)}%"><i style="width:${Math.round(f.score * 100)}%"></i></div>
    <div class="tp">${D.topics[f.topic].icon} ${esc(D.topics[f.topic].label)}</div>
    <div class="v">${esc(f.display)}</div><div class="t">${esc(f.title)}</div>
    <div class="why">${f.used ? '✓ ' : '· '}${esc(f.reason)}</div>
    <div class="meta"><span class="chip ${tw[1]} trust" tabindex="0">${tw[0]}<span class="pop">${esc(f.detail || '')}${f.detail ? '<br>' : ''}From: ${esc(f.sources.join(', '))}</span></span>${link}</div></div>`; }
function draw() {
  const inTopic = f => topic === 'all' || f.topic === topic;
  const used = D.facts.filter(f => f.used && inTopic(f)), rest = D.facts.filter(f => !f.used && inTopic(f));
  const counts = {}; D.facts.forEach(f => { counts[f.topic] = counts[f.topic] || [0, 0]; counts[f.topic][0]++; if (f.used) counts[f.topic][1]++; });
  const chips = ['all', ...Object.keys(D.topics).filter(t => counts[t])].map(t => `<button class="fchip ${t === topic ? 'on' : ''}" data-t="${t}">${t === 'all' ? 'All topics' : D.topics[t].icon + ' ' + esc(D.topics[t].label)}<i>${t === 'all' ? D.counts.used : counts[t][1]}</i></button>`).join('');
  document.getElementById('kl').innerHTML = `<div class="head"><div><h3>🧠 What the knowledge layer says about ${esc(L.label)}</h3>
      <div class="sub">Every fact comes from a data source and carries its trust level. Only what matters for the ${esc(C.emoji)} ${esc(C.title)} is shown first; the bar on each card is its relevance.</div></div>
      <div class="funnel"><span><b>${D.counts.total}</b> facts known</span><span class="arr">→</span><span><b class="u">${D.counts.used}</b> matter for ${esc(C.audience_short)}</span><span class="muted">from ${D.counts.sources} sources</span></div></div>
    <div class="fchips">${chips}</div>
    <div class="kgrid">${used.map(card).join('') || '<div class="muted" style="font-size:13px;padding:8px 2px">Nothing in this topic matters for this campaign.</div>'}</div>
    ${rest.length ? `<button class="more" id="more">${showAll ? '▾ Hide' : '▸ Show'} the other ${rest.length} fact${rest.length > 1 ? 's' : ''} we know (not used for this campaign)</button>` : ''}
    ${showAll ? `<div class="kgrid">${rest.map(card).join('')}</div>` : ''}`;
  document.querySelectorAll('.fchip').forEach(b => b.onclick = () => { topic = b.dataset.t; draw(); });
  const m = document.getElementById('more'); if (m) m.onclick = () => { showAll = !showAll; draw(); };
  fit();
}
draw();
"""


def explore_html(data: dict) -> str:
    return _doc(_EXPLORE_CSS, _EXPLORE_BODY, _EXPLORE_JS, data)


# --------------------------------------------------------------------------- score & compare


_SCORE_CSS = r"""
.sgrid { display:grid; grid-template-columns:300px 1fr; gap:16px; align-items:start; }
@media (max-width:900px) { .sgrid { grid-template-columns:1fr; } }
.wts { padding:16px 18px; position:sticky; top:4px; }
.wts h4 { margin:0; font-size:14.5px; } .wts .sub { font-size:12px; color:var(--muted); margin:2px 0 10px; }
.w { margin:10px 0; } .w .top { display:flex; justify-content:space-between; font-size:13px; font-weight:700; }
.w .top span:last-child { color:var(--accent); } .w .help { font-size:11.5px; color:var(--muted); margin-top:2px; }
.w input { width:100%; accent-color:var(--cc); margin:6px 0 0; }
.w .flat { font-size:11px; color:var(--warn-text); font-weight:600; }
.reset { font:inherit; font-size:12.5px; font-weight:700; border:1px solid var(--line); background:#fff; border-radius:999px; padding:5px 12px; cursor:pointer; color:var(--ink2); }
.rows { position:relative; }
.row { padding:14px 16px; margin-bottom:10px; transition:transform .45s cubic-bezier(.2,.8,.2,1), box-shadow .2s; cursor:pointer; }
.row .top { display:grid; grid-template-columns:40px 1fr auto; gap:12px; align-items:center; }
.medal { font-size:24px; text-align:center; }
.row h5 { margin:0; font-size:16px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.row h5 i { width:10px; height:10px; border-radius:50%; display:inline-block; }
.row .rd { font-size:12.5px; color:var(--ink2); margin-top:2px; }
.tot { text-align:right; } .tot b { font-size:28px; letter-spacing:-.02em; } .tot span { font-size:11.5px; color:var(--muted); display:block; }
.stack { display:flex; height:12px; border-radius:999px; overflow:hidden; background:var(--soft); margin-top:10px; gap:2px; }
.stack i { display:block; height:100%; transition:width .5s cubic-bezier(.2,.8,.2,1); }
.det { display:none; margin-top:12px; gap:8px; flex-direction:column; }
.row.open .det { display:flex; }
.cr { display:grid; grid-template-columns:150px 1fr 40px; gap:10px; align-items:center; font-size:12.5px; }
.cr .bar { height:8px; border-radius:999px; background:var(--soft); overflow:hidden; } .cr .bar i { display:block; height:100%; border-radius:999px; }
.cr b { text-align:right; } .cr .why { grid-column:2 / 4; font-size:12px; color:var(--ink2); margin-top:-4px; }
.focusr { box-shadow:0 0 0 2px var(--accent), var(--shadow); }
.leg { display:flex; gap:12px; flex-wrap:wrap; font-size:12px; color:var(--ink2); margin:0 2px 10px; }
.leg i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
.recon { padding:14px 18px; margin-top:6px; border-left:4px solid var(--accent); font-size:13.5px; line-height:1.55; color:var(--ink2); }
.recon b { color:var(--ink); }
.row .out { grid-column:1/-1; margin-top:8px; padding:8px 10px; border-radius:10px; background:#fff7e6; color:#7a4b00; font-size:12.5px; line-height:1.45; }
.across { padding:16px 18px; margin-top:16px; }
.across h4 { margin:0; font-size:14.5px; } .across .sub { font-size:12px; color:var(--muted); margin:2px 0 10px; }
.mx { width:100%; border-collapse:separate; border-spacing:4px; font-size:13px; }
.mx th { font-size:12px; color:var(--ink2); font-weight:700; text-align:center; padding:4px; }
.mx th:first-child { text-align:left; }
.mx td { text-align:center; border-radius:10px; padding:10px 6px; font-weight:800; transition:transform .15s; }
.mx td:first-child { text-align:left; font-weight:700; background:none; }
.mx td.cell:hover { transform:scale(1.04); }
.mx tr.cur td:first-child { color:var(--accent); }
"""

_SCORE_BODY = r"""<div class="sgrid"><div class="wts card fade" id="wts"></div><div><div class="leg" id="leg"></div><div class="rows" id="rows"></div><div class="recon card fade" id="recon"></div></div></div><div class="across card fade" id="across"></div>"""

_SCORE_JS = _ESC_JS + r"""
const CC = ['#6250d6', '#2a78d6', '#1baf7a', '#eb6834', '#8a889c'];
const W = Object.assign({}, D.weights);
const crit = D.criteria;
document.getElementById('leg').innerHTML = crit.map((c, i) => `<span><i style="background:${CC[i]}"></i>${c.icon} ${esc(c.label)}</span>`).join('');
function drawWts() {
  document.getElementById('wts').innerHTML = `<h4>⚖️ What matters most?</h4><div class="sub">Move the weights; the ranking updates instantly. Defaults are set for the ${esc(D.campaign.emoji)} ${esc(D.campaign.title)}.</div>
    ${crit.map((c, i) => `<div class="w" style="--cc:${CC[i]}"><div class="top"><span>${c.icon} ${esc(c.label)}</span><span id="wv-${c.id}">${Math.round(100 * W[c.id] / Object.values(W).reduce((a, b) => a + b, 0) || 0)}%</span></div>
      <input type="range" min="0" max="50" step="5" value="${W[c.id]}" data-k="${c.id}"><div class="help">${esc(c.help)}</div>${c.flat ? '<div class="flat">Barely differs between locations</div>' : ''}</div>`).join('')}
    <button class="reset" id="reset">Reset to campaign defaults</button>`;
  document.querySelectorAll('.w input').forEach(s => s.oninput = () => { W[s.dataset.k] = +s.value; rank(); });
  document.getElementById('reset').onclick = () => { Object.assign(W, D.weights); drawWts(); rank(); };
}
const open = new Set([D.focus]);
function total(l) { const sw = Object.values(W).reduce((a, b) => a + b, 0) || 1;
  return crit.reduce((s, c) => s + W[c.id] * l.scores[c.id].score, 0) / sw; }
const rowsEl = document.getElementById('rows');
D.locs.forEach(l => { const d = document.createElement('div'); d.className = 'row card lift' + (l.focus ? ' focusr' : ''); d.id = 'r-' + l.id;
  d.onclick = () => { open.has(l.id) ? open.delete(l.id) : open.add(l.id); d.classList.toggle('open'); fit(); };
  if (open.has(l.id)) d.classList.add('open'); rowsEl.appendChild(d); });
function rank() {
  const sw = Object.values(W).reduce((a, b) => a + b, 0) || 1;
  crit.forEach(c => { const el = document.getElementById('wv-' + c.id); if (el) el.textContent = Math.round(100 * W[c.id] / sw) + '%'; });
  const order = D.locs.map(l => ({ l, t: total(l) })).sort((a, b) => b.t - a.t);
  const first = {}; order.forEach(o => first[o.l.id] = document.getElementById('r-' + o.l.id).getBoundingClientRect().top);
  order.forEach((o, i) => { const l = o.l, d = document.getElementById('r-' + l.id);
    d.innerHTML = `<div class="top"><div class="medal">${['🥇','🥈','🥉'][i] || '#' + (i + 1)}</div>
      <div><h5><i style="background:${l.color}"></i>${esc(l.label)} ${l.in_plan ? '<span class="chip accent">⭐ in our plan</span>' : ''}</h5><div class="rd">${esc(l.road)} · ${esc(l.format)}</div></div>
      <div class="tot"><b data-v="${o.t}">${Math.round(o.t)}</b><span>score / 100</span></div></div>
      <div class="stack">${crit.map((c, k) => `<i style="width:${(W[c.id] * l.scores[c.id].score / sw).toFixed(2)}%;background:${CC[k]}" title="${esc(c.label)}: ${Math.round(l.scores[c.id].score)}"></i>`).join('')}</div>
      <div class="det">${crit.map((c, k) => `<div class="cr"><span>${c.icon} ${esc(c.label)}</span><div class="bar"><i style="width:${l.scores[c.id].score}%;background:${CC[k]}"></i></div><b>${Math.round(l.scores[c.id].score)}</b><div class="why">${esc(l.scores[c.id].why)}</div></div>`).join('')}${l.why_out ? `<div class="out">🧾 <b>Why it is not in our plan:</b> ${esc(l.why_out)}</div>` : ''}</div>`;
    rowsEl.appendChild(d); });
  if (!reduce) order.forEach(o => { const d = document.getElementById('r-' + o.l.id), dy = first[o.l.id] - d.getBoundingClientRect().top;
    if (dy) { d.style.transition = 'none'; d.style.transform = `translateY(${dy}px)`; requestAnimationFrame(() => { d.style.transition = ''; d.style.transform = ''; }); } });
  const top = order[0].l;
  const planNames = D.plan.join(', ');
  document.getElementById('recon').innerHTML = top.in_plan
    ? `🎯 <b>${esc(top.label)} scores highest and is in our plan</b> (${esc(planNames)}). The plan also counts drivers who pass several boards only once, so it can include boards that score lower here.`
    : `🤔 <b>${esc(top.label)} scores highest on its own, but our plan (${esc(planNames)}) leaves it out</b>: ${esc(top.why_out)} The score rates each board alone; the plan picks the best <i>set</i> for the brief's number of boards.`;
  fit();
}
drawWts(); rank();
// ---- across campaigns
(function () {
  const A = D.across; if (!A) return;
  const col = v => `color-mix(in srgb, #6250d6 ${Math.round(8 + v * .55)}%, white)`;
  document.getElementById('across').innerHTML = `<h4>🗂️ Every campaign at a glance</h4><div class="sub">Score of each location for each campaign (default weights). ⭐ = in that campaign's plan.</div>
    <table class="mx"><tr><th></th>${A.locs.map(l => `<th>${esc(l.label)}</th>`).join('')}</tr>
    ${A.campaigns.map(c => `<tr class="${c.id === D.campaign.id ? 'cur' : ''}"><td>${esc(c.emoji)} ${esc(c.title)}</td>${A.locs.map(l => { const v = c.totals[l.id];
      return `<td class="cell" style="background:${col(v)};color:${v > 70 ? '#fff' : 'var(--ink)'}" title="${esc(c.title)} · ${esc(l.label)}">${Math.round(v)}${c.plan.includes(l.id) ? ' ⭐' : ''}</td>`; }).join('')}</tr>`).join('')}</table>`;
  fit();
})();
"""


def score_html(data: dict) -> str:
    return _doc(_SCORE_CSS, _SCORE_BODY, _SCORE_JS, data)


# --------------------------------------------------------------------------- the brief, answered

# The brief's four labels, and how the engine's labels map onto them.
BRIEF_LABELS = [
    ("Confirmed", "good", "From an official or named source", "RTA: 2,000 vehicles per lane per hour"),
    ("Estimate", "accent", "Calculated from confirmed data plus a stated assumption", "Unique people a month"),
    ("Assumption", "warn", "A setting we chose; editable in the tool", "1.5 people per vehicle"),
    ("Concept", "crit", "Needs a partner or further validation", "Targeting the exact people who passed"),
]
ENGINE_TO_BRIEF = {"VERIFIED": "Confirmed", "ESTIMATE": "Estimate", "SAMPLE": "Estimate on sample inputs",
                   "ASSUMPTION": "Assumption", "CONCEPT": "Concept"}

_BRIEF_CSS = r"""
h2.sec { font-size:17px; margin:22px 0 10px; display:flex; align-items:center; gap:8px; }
h2.sec .chip { font-size:11px; }
.hero { padding:22px 24px; display:grid; grid-template-columns:1.25fr 1fr; gap:22px; align-items:center;
        background:linear-gradient(135deg,#ffffff 0%,#f4f2ff 100%); }
@media (max-width:860px) { .hero { grid-template-columns:1fr; } }
.hero .eb { font-size:12px; font-weight:700; letter-spacing:.08em; color:var(--accent); text-transform:uppercase; }
.hero h3 { font-size:22px; line-height:1.3; margin:6px 0 8px; letter-spacing:-.01em; }
.hero p { margin:0; color:var(--ink2); font-size:14px; line-height:1.5; }
.stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.st { background:#fff; border:1px solid var(--line); border-radius:14px; padding:12px 14px; }
.st .v { font-size:26px; font-weight:800; letter-spacing:-.02em; }
.st .k { font-size:12px; color:var(--ink2); margin-top:2px; line-height:1.35; }
.boards { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }
.bd { display:inline-flex; align-items:center; gap:6px; font-size:13px; font-weight:600; padding:4px 10px; border-radius:999px;
      background:#fff; border:1px solid var(--line); }
.bd i { width:9px; height:9px; border-radius:50%; background:var(--c); }
table.cmp { width:100%; border-collapse:separate; border-spacing:0; font-size:13.5px; }
table.cmp th { text-align:right; font-size:11.5px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.04em;
               padding:12px 14px; border-bottom:1px solid var(--line); }
table.cmp th:first-child, table.cmp td:first-child { text-align:left; }
table.cmp td { text-align:right; padding:12px 14px; border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }
table.cmp tr:last-child td { border-bottom:none; }
table.cmp tr:hover td { background:var(--soft); }
table.cmp .nm b { font-size:14px; } table.cmp .nm span { display:block; font-size:12px; color:var(--muted); }
table.cmp .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; background:var(--c); }
table.cmp .rng { display:block; font-size:11.5px; color:var(--muted); }
table.cmp .best { color:var(--good-text); font-weight:800; }
.cmpwrap { padding:4px 6px; overflow-x:auto; }
.note { font-size:12px; color:var(--muted); line-height:1.5; margin-top:8px; }
.legend { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
@media (max-width:860px) { .legend { grid-template-columns:1fr 1fr; } }
.lg { padding:12px 14px; } .lg p { margin:6px 0 0; font-size:12.5px; color:var(--ink2); line-height:1.4; }
.lg .ex { font-size:11.5px; color:var(--muted); margin-top:4px; }
.cols3 { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
@media (max-width:860px) { .cols3 { grid-template-columns:1fr; } }
.capcol { padding:14px 16px; } .capcol h4 { margin:0 0 8px; font-size:14px; display:flex; gap:8px; align-items:center; }
.cap { padding:9px 0; border-top:1px solid var(--line); } .cap b { font-size:13.5px; } .cap p { margin:2px 0 0; font-size:12.5px; color:var(--ink2); }
.src { display:grid; grid-template-columns:1.4fr 2fr 70px; gap:12px; align-items:center; padding:9px 14px; }
.src + .src { border-top:1px solid var(--line); }
.src .n b { font-size:13.5px; } .src .n span { display:block; font-size:11.5px; color:var(--muted); }
.bar { position:relative; height:12px; background:var(--soft); border-radius:999px; overflow:hidden; }
.bar .pot { position:absolute; inset:0 auto 0 0; background:#dcd7fb; border-radius:999px; }
.bar .now { position:absolute; inset:0 auto 0 0; background:var(--accent); border-radius:999px; transition:width 1s cubic-bezier(.2,.8,.2,1); }
.src .sc { font-size:13px; font-weight:700; text-align:right; white-space:nowrap; } .src .sc span { color:var(--muted); font-weight:500; }
.src.top { background:#f4f2ff; border-radius:12px; }
.ai { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
@media (max-width:860px) { .ai { grid-template-columns:1fr 1fr; } }
.tbl { width:100%; border-collapse:collapse; font-size:13px; }
.tbl th { text-align:left; font-size:11.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; padding:10px 14px; border-bottom:1px solid var(--line); }
.tbl td { padding:10px 14px; border-bottom:1px solid var(--line); vertical-align:top; line-height:1.45; color:var(--ink2); }
.tbl td:first-child { color:var(--ink); font-weight:600; } .tbl tr:last-child td { border-bottom:none; }
.road { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
@media (max-width:960px) { .road { grid-template-columns:1fr 1fr; } }
.ph { padding:14px 16px; position:relative; } .ph .w { font-size:12px; font-weight:700; color:var(--accent); }
.ph h4 { margin:4px 0 6px; font-size:14.5px; } .ph p { margin:0; font-size:12.5px; color:var(--ink2); line-height:1.45; }
.ph .g { margin-top:8px; font-size:11.5px; color:var(--muted); } .ph.done { border-color:#cdeccd; background:#f6fcf6; }
.opt { padding:16px; } .opt .v { display:flex; align-items:center; gap:4px; margin:10px 0 8px; } .opt .v .k { font-size:12px; font-weight:650; color:var(--muted); }
.opt .v .dots i { width:10px; height:10px; } .opt p { margin:0; font-size:12.5px; color:var(--ink2); line-height:1.45; }
.opt.rec { border:2px solid var(--accent); }
.val { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; }
@media (max-width:960px) { .val { grid-template-columns:1fr 1fr; } }
.vl { padding:12px 14px; } .vl b { font-size:13.5px; } .vl p { margin:4px 0 0; font-size:12.5px; color:var(--ink2); line-height:1.4; }
"""

_BRIEF_JS = r"""
const root = document.getElementById('root');
function chip(t, k) { return `<span class="chip ${k || ''}">${t}</span>`; }
function sec(icon, title, extra) { return `<h2 class="sec">${icon} ${title} ${extra || ''}</h2>`; }
let h = '';
if (D.view === 'answer') {
  const p = D.plan;
  const nb = p.names.length;
  h += `<div class="hero card fade"><div><div class="eb">${D.campaign.emoji} ${D.campaign.title} · ${D.campaign.when} · ${D.campaign.boards} boards</div>
    <h3>Book ${p.names.join(', ').replace(/, ([^,]*)$/, ' and $1')} (${nb} board${nb === 1 ? '' : 's'}).</h3>
    <p>Together they reach about <b>${fmtP(p.audience)} ${D.campaign.aud}</b> a month, each person counted once;
    ${fmtP(p.dup)} people who pass more than one of them are not counted twice. No other mix of ${nb} boards reaches more.</p>
    <div class="boards">${p.boards.map(b => `<span class="bd" style="--c:${b.color}"><i></i>${b.label}</span>`).join('')}</div></div>
    <div class="stats"><div class="st"><div class="v" id="s1">–</div><div class="k">${D.campaign.aud} reached a month</div></div>
      <div class="st"><div class="v" id="s2">${nb}</div><div class="k">boards booked, as the brief asks</div></div>
      <div class="st"><div class="v" id="s3">–</div><div class="k">counted twice, removed</div></div></div></div>`;
} else if (D.view === 'table') {
  h += sec('📊', 'How the four billboards compare', chip(D.label_note, 'accent'));
  h += `<div class="card cmpwrap fade"><table class="cmp"><tr><th>Billboard</th><th>Impressions / day</th><th>Unique people / month</th>
    <th>${D.aud_cap} / month</th><th title="Our 1-4 rating, no prices used">Price level</th><th title="Target audience for the price level (a rating)">Value</th></tr>`;
  D.rows.forEach(r => { h += `<tr><td class="nm"><span class="dot" style="--c:${r.color}"></span><b>${r.label}</b>${r.in_plan ? ' ⭐' : ''}<span>${r.road}</span></td>
    <td>${fmtP(r.imp)}</td><td>${fmtP(r.uniq)}<span class="rng">${fmtP(r.uniq_lo)}–${fmtP(r.uniq_hi)}</span></td><td>${fmtP(r.rel)}</td>
    <td>${dots(r.price_dots, 4)}</td><td class="${r.best ? 'best' : ''}">${dots(r.value_dots, 4)}${r.best ? ' 💎' : ''}</td></tr>`; });
  h += `</table></div><div class="note">⭐ in the recommended plan · 💎 most audience for its price level. Price level is our 1-4 rating; no prices are used.
    Unique people show the low–high range: how often a person passes each month is the weakest input until mobile data is connected.</div>`;
  h += sec('🏷️', 'How to read every number');
  h += `<div class="legend">${D.legend.map((l, i) => `<div class="lg card fade" style="animation-delay:${.05 * i}s">${chip(l[0], l[1])}<p>${l[2]}</p><div class="ex">e.g. ${l[3]}</div></div>`).join('')}</div>`;
} else if (D.view === 'real') {
  h += sec('🔍', 'How much can be solved today', chip('Area 1', 'accent'));
  const cols = [['today', '✅', 'Achievable today', 'good'], ['estimate', '📐', 'Estimate today, measured later', 'accent'], ['concept', '💡', 'Concept: needs a partner', 'crit']];
  h += `<div class="cols3">${cols.map((c, i) => `<div class="capcol card fade" style="animation-delay:${.06 * i}s"><h4>${c[1]} ${c[2]}</h4>
    ${D.caps.filter(x => x.status === c[0]).map(x => `<div class="cap"><b>${x.what}</b><p>${x.why}</p></div>`).join('')}</div>`).join('')}</div>`;
  h += sec('📡', 'How solid each data source is: today → once connected', chip('Area 2 · live from the source registry', 'accent'));
  h += `<div class="card fade" style="padding:6px">${D.sources.map(s => `<div class="src ${s.top ? 'top' : ''}"><div class="n"><b>${s.name}</b><span>${s.status}${s.top ? ' · biggest single gain' : ''}</span></div>
    <div class="bar" title="Today ${s.score} · once connected ${s.potential}"><div class="pot" style="width:${s.potential}%"></div><div class="now" style="width:0" data-w="${s.score}"></div></div>
    <div class="sc">${s.score}<span> → ${s.potential}</span></div></div>`).join('')}</div>
    <div class="note">Confidence 0–100: who provides the data, how directly it measures audiences and how fresh it is. Dark bar = today, light bar = once connected.</div>`;
  h += sec('🤖', 'What the AI does, and what it never does');
  h += `<div class="ai">${D.ai.map((a, i) => `<div class="st card fade" style="animation-delay:${.05 * i}s"><div class="v">${a.v}</div><div class="k">${a.k}</div></div>`).join('')}</div>
    <div class="note">${D.ai_note}</div>`;
  h += sec('📲', 'Re-engaging people who passed', chip('Area 5', 'accent'));
  h += `<div class="card fade"><table class="tbl"><tr><th>Route</th><th>Feasibility</th><th>Precision</th></tr>
    ${D.routes.map(r => `<tr><td>${r.route}</td><td>${r.feasibility.startsWith('Feasible today') ? chip('✅ ' + r.feasibility, 'good') : chip(r.feasibility, 'warn')}</td><td>${r.precision}</td></tr>`).join('')}</table></div>
    <div class="note">UAE Personal Data Protection Law: consented, grouped data only. Meta and Google target areas of about 1 km, not exact passers-by.</div>`;
} else {
  h += sec('🗺️', 'Roadmap', chip('Plan, not computed', 'warn'));
  h += `<div class="road">${D.roadmap.map((r, i) => `<div class="ph card fade ${r.when === 'Done' ? 'done' : ''}" style="animation-delay:${.06 * i}s"><div class="w">${r.when === 'Done' ? '✅ Done' : r.when}</div>
    <h4>${r.phase}</h4><p>${r.adds}</p><div class="g">Go-ahead: ${r.gate}</div></div>`).join('')}</div><div class="note"><b>${D.roadmap_total}</b></div>`;
  h += sec('🧩', 'Options: what each one needs', chip('Plan, not computed', 'warn'));
  h += `<div class="cols3">${D.costs.map((c, i) => `<div class="opt card fade ${c.recommended ? 'rec' : ''}" style="animation-delay:${.06 * i}s">
    ${chip((c.recommended ? '⭐ ' : '') + c.option, c.recommended ? 'accent' : '')}<div class="v"><span class="k">Data needed</span>${dots(c.data_needed, 3)}</div><p>${c.what}</p></div>`).join('')}</div>
    <div class="note">Development is in-house. Maintenance: ${D.maintenance}</div>`;
  h += sec('⚠️', 'Risks and how we handle them');
  h += `<div class="card fade"><table class="tbl"><tr><th>Risk</th><th>Impact</th><th>How we handle it</th></tr>
    ${D.risks.map(r => `<tr><td>${r.risk}</td><td>${r.impact}</td><td>${r.handle}</td></tr>`).join('')}</table></div>`;
  h += sec('🏆', 'Business value');
  h += `<div class="val">${D.value.map((v, i) => `<div class="vl card fade" style="animation-delay:${.05 * i}s"><b>${v.title}</b><p>${v.text}</p></div>`).join('')}</div>
    <div class="note"><b>What it will not do at first:</b> ${D.not_at_first}</div>`;
}
root.innerHTML = h;
if (D.view === 'answer') { tween(document.getElementById('s1'), D.plan.audience, fmtP, 1100);
  tween(document.getElementById('s3'), D.plan.dup, fmtP, 1100); }
setTimeout(() => document.querySelectorAll('.now').forEach(b => b.style.width = b.dataset.w + '%'), reduce ? 0 : 200);
fit();
"""


def brief_html(data: dict) -> str:
    """One section of 'The brief, answered' (data['view']: answer / table / real / path)."""
    return _doc(_BRIEF_CSS, '<div id="root"></div>', _BRIEF_JS, data)
