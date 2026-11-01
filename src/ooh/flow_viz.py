"""Animated "data sources -> knowledge layer -> outcomes" diagram (replaces the old brain picture).

Input is the dict from :func:`ooh.knowledge.flow_graph` for the focus campaign, plus
``campaigns`` (one flow graph per campaign, so the selector switches in the browser without a
Streamlit rerun) and ``focus_campaign``. Every count and link is read from the facts, so the
picture cannot drift from the code:

* particles run only on links that carry facts the selected campaign uses;
* links whose facts are not used by this campaign stay faint;
* sources that are not connected have no facts, so they are drawn dashed with no links.

Hover a card to trace it, click to pin, click the background to release.
"""

from __future__ import annotations

from .exec_ui import _doc

_CSS = r"""
body { position:relative; }
.top { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin:2px 2px 10px; }
.head { font-size:15px; font-weight:700; color:var(--ink); }
.head b { color:var(--accent); font-size:20px; font-variant-numeric:tabular-nums; }
.head span.muted { font-weight:500; font-size:13px; }
.camps { display:flex; gap:8px; flex-wrap:wrap; }
.camp { font:inherit; font-size:13px; font-weight:700; border:1.5px solid var(--line); background:#fff; color:var(--ink2);
        border-radius:999px; padding:6px 13px; cursor:pointer; transition:transform .15s, border-color .2s, background .2s, color .2s; }
.camp:hover { transform:translateY(-2px); }
.camp.on { border-color:var(--accent); background:var(--accent-soft); color:var(--ink); }
.stage { padding:10px 8px 6px; }
svg { display:block; width:100%; height:auto; overflow:visible; }
.col { font-size:11.5px; font-weight:800; letter-spacing:.12em; fill:var(--muted); text-transform:uppercase; }
.node { cursor:pointer; transition:opacity .25s; }
.node .bg { fill:#fff; stroke:var(--line); stroke-width:1; transition:stroke .2s, fill .2s; }
.node:hover .bg, .node.focus .bg { stroke:var(--accent); fill:#f7f5ff; }
.node.off .bg { fill:#fbfbfd; stroke-dasharray:4 4; }
.node.off text { fill:#a5a3b6; }
.nm { font-size:13px; font-weight:700; fill:var(--ink); }
.sb { font-size:10.5px; fill:var(--muted); }
.ct { font-size:12px; font-weight:800; fill:var(--ink); font-variant-numeric:tabular-nums; }
.pill { font-size:9.5px; font-weight:800; letter-spacing:.03em; }
.panel { fill:url(#kgrad); stroke:#dcd7fb; stroke-width:1.2; }
.ptitle { font-size:15px; font-weight:800; fill:var(--accent); }
.psub { font-size:11px; fill:var(--ink2); }
.shelf .bg { fill:#fff; stroke:#e7e4f7; }
.shelf .bar { fill:var(--line); }
.shelf .fill { fill:var(--accent); transition:width .7s cubic-bezier(.2,.8,.2,1); }
.icon { font-size:15px; }
.link { fill:none; stroke-linecap:round; transition:opacity .35s, stroke .35s, stroke-width .35s; }
.link.cold { opacity:.13; }
.link.hot { opacity:.42; }
.dim { opacity:.1 !important; }
.node.dim { opacity:.28 !important; }
.trace { opacity:.95 !important; }
.pt { pointer-events:none; }
.legend { display:flex; gap:16px; flex-wrap:wrap; align-items:center; font-size:12px; color:var(--ink2); margin:8px 4px 2px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; vertical-align:-1px; }
.legend i.dash { border:1.5px dashed #b4b2c4; background:#fff; }
#tip { position:absolute; z-index:30; pointer-events:none; max-width:320px; background:#fff; border:1px solid var(--line);
       border-radius:12px; padding:10px 12px; font-size:12.5px; line-height:1.45; box-shadow:var(--shadow-up);
       opacity:0; transform:translateY(4px); transition:opacity .15s, transform .15s; }
#tip.show { opacity:1; transform:none; }
#tip h4 { margin:0 0 3px; font-size:14px; }
#tip .muted { font-size:11.5px; }
#tip .ex { margin-top:6px; padding-top:6px; border-top:1px solid var(--line); color:var(--ink2); }
"""

_BODY = r"""
<div class="top"><div class="head" id="head"></div><div class="camps" id="camps"></div></div>
<div class="card stage fade"><svg id="viz" role="img" aria-label="Data sources feed a knowledge layer; each campaign uses only the facts it needs"></svg>
<div class="legend">
  <span><i style="background:#0ca30c"></i>live, cached or configured</span>
  <span><i style="background:#eda100"></i>placeholder (sample)</span>
  <span><i style="background:#12a4b4"></i>on demand</span>
  <span><i class="dash"></i>not connected / Phase 2</span>
  <span>● moving dots = facts this campaign uses · faint lines = known but not needed here</span>
</div></div>
<div id="tip"></div>
"""

_JS = r"""
const NS = 'http://www.w3.org/2000/svg';
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STATUS = { live:['#0ca30c','LIVE'], cached:['#0ca30c','CACHED'], configured:['#0ca30c','CONFIGURED'],
                 sample:['#eda100','PLACEHOLDER'], 'on demand':['#12a4b4','ON DEMAND'], 'not connected':['#b4b2c4','NOT CONNECTED'] };
const st = s => STATUS[s.status] || ['#8a889c', String(s.status || '').toUpperCase()];
const svg = document.getElementById('viz'), tip = document.getElementById('tip');
const camps = (D.campaigns && D.campaigns.length) ? D.campaigns
  : [{ id: D.campaign.id, title: D.campaign.title, emoji: D.campaign.emoji, audience_short: D.campaign.audience_short, graph: D }];
let cur = camps.find(c => c.id === D.focus_campaign) || camps[0];
const base = cur.graph;

// ---- layout
const W = 1200, ROW = 52, TOP = 44;
const S = base.sources, T = base.topics, O = base.outcomes;
const H = TOP + Math.max(S.length * ROW, T.length * 62 + 70, O.length * 74) + 10;
svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
const SX = 8, SW = 280, KX = 430, KW = 340, OX = 922, OW = 270;
const sy = i => TOP + i * ROW;
const kTop = TOP, kH = H - TOP - 8, shelfH = Math.min(52, (kH - 74) / T.length - 8);
const ty = i => kTop + 62 + i * ((kH - 70) / T.length);
const oy = i => TOP + (H - TOP - O.length * 74) / 2 + i * 74;
function el(tag, attrs, parent) { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); (parent || svg).appendChild(e); return e; }
function txt(p, x, y, s, cls, extra) { const t = el('text', Object.assign({ x, y, class: cls }, extra || {}), p); t.textContent = s; return t; }
const clip = (s, n) => (s = String(s || '')).length > n ? s.slice(0, n - 1) + '…' : s;

const defs = el('defs', {});
defs.innerHTML = `<linearGradient id="kgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f4f1ff"/><stop offset="1" stop-color="#fbfaff"/></linearGradient>`;
txt(svg, SX, 20, 'Data sources', 'col'); txt(svg, KX, 20, 'Knowledge layer', 'col'); txt(svg, OX, 20, 'Outcomes', 'col');
const gLinks = el('g', {}), gPts = el('g', {}), gNodes = el('g', {});

// knowledge panel
const panel = el('g', {}, gNodes);
el('rect', { x: KX, y: kTop, width: KW, height: kH, rx: 18, class: 'panel' }, panel);
txt(panel, KX + 18, kTop + 26, '🗄️ Knowledge layer', 'ptitle');
const pSub = txt(panel, KX + 18, kTop + 44, '', 'psub');

// ---- nodes
const pos = {};   // id -> {in:[x,y], out:[x,y]}
const nodes = {};
S.forEach((s, i) => {
  const y = sy(i), [col, word] = st(s), off = s.status === 'not connected' || !s.facts;
  const g = el('g', { class: 'node' + (off ? ' off' : ''), 'data-id': 's:' + s.id }, gNodes);
  el('rect', { x: SX, y, width: SW, height: ROW - 8, rx: 11, class: 'bg' }, g);
  el('rect', { x: SX, y: y + 8, width: 3.5, height: ROW - 24, rx: 2, fill: col }, g);
  txt(g, SX + 14, y + 18, clip(s.name, 30), 'nm');
  const ctx = s.context_only || (Array.isArray(s.feeds) && s.feeds.length === 0 && s.facts > 0);
  // status pill on the second line, so long names keep the full first line
  const pw = word.length * 5.6 + 12;
  el('rect', { x: SX + 14, y: y + 24, width: pw, height: 14, rx: 7, fill: off ? '#f1f0f6' : col, opacity: off ? 1 : .14 }, g);
  txt(g, SX + 14 + pw / 2, y + 34, word, 'pill', { 'text-anchor': 'middle', fill: off ? '#8a889c' : col });
  txt(g, SX + 20 + pw, y + 34, ctx ? 'context only' : clip(s.provider, Math.max(6, Math.floor((150 - pw) / 5.2))), 'sb');
  // confidence ring
  const cx = SX + SW - 20, cy = y + (ROW - 8) / 2, r = 11, C = 2 * Math.PI * r;
  el('circle', { cx, cy, r, fill: 'none', stroke: '#ecebf3', 'stroke-width': 3.5 }, g);
  el('circle', { cx, cy, r, fill: 'none', stroke: col, 'stroke-width': 3.5, 'stroke-dasharray': `${C * (s.score || 0) / 100} ${C}`,
                 transform: `rotate(-90 ${cx} ${cy})`, 'stroke-linecap': 'round' }, g);
  txt(g, cx, cy + 3.5, String(s.score || 0), 'pill', { 'text-anchor': 'middle', fill: '#55536a' });
  const fc = txt(g, SX + SW - 44, y + 33, '', 'sb', { 'text-anchor': 'end' });
  nodes['s:' + s.id] = { g, data: s, kind: 's', count: fc };
  pos['s:' + s.id] = { out: [SX + SW, y + (ROW - 8) / 2] };
});
T.forEach((t, i) => {
  const y = ty(i), g = el('g', { class: 'node shelf', 'data-id': 't:' + t.id }, gNodes);
  el('rect', { x: KX + 14, y, width: KW - 28, height: shelfH, rx: 10, class: 'bg' }, g);
  txt(g, KX + 26, y + shelfH / 2 - 2, t.icon || '•', 'icon');
  txt(g, KX + 50, y + shelfH / 2 - 3, t.label, 'nm');
  const c = txt(g, KX + KW - 26, y + shelfH / 2 - 3, '', 'ct', { 'text-anchor': 'end' });
  el('rect', { x: KX + 50, y: y + shelfH / 2 + 5, width: KW - 76, height: 5, rx: 2.5, class: 'bar' }, g);
  const f = el('rect', { x: KX + 50, y: y + shelfH / 2 + 5, width: 0, height: 5, rx: 2.5, class: 'fill' }, g);
  nodes['t:' + t.id] = { g, data: t, kind: 't', count: c, fill: f };
  pos['t:' + t.id] = { in: [KX + 14, y + shelfH / 2], out: [KX + KW - 14, y + shelfH / 2] };
});
O.forEach((o, i) => {
  const y = oy(i), g = el('g', { class: 'node', 'data-id': 'o:' + o.id }, gNodes);
  el('rect', { x: OX, y, width: OW, height: 60, rx: 14, class: 'bg' }, g);
  txt(g, OX + 16, y + 37, o.icon || '•', 'icon', { style: 'font-size:22px' });
  txt(g, OX + 52, y + 27, o.label, 'nm');
  const c = txt(g, OX + 52, y + 44, '', 'sb');
  nodes['o:' + o.id] = { g, data: o, kind: 'o', count: c };
  pos['o:' + o.id] = { in: [OX, y + 30] };
});

// ---- links (union over campaigns; n is campaign-free, used varies)
const links = {};
function curve(a, b) { const dx = (b[0] - a[0]) * .5; return `M${a[0]},${a[1]} C${a[0] + dx},${a[1]} ${b[0] - dx},${b[1]} ${b[0]},${b[1]}`; }
function addLink(from, to, n, color) {
  const key = from + '>' + to; if (links[key] || !pos[from] || !pos[to]) return;
  const p = el('path', { d: curve(pos[from].out, pos[to].in), class: 'link cold', stroke: color, 'stroke-width': Math.max(1.2, Math.sqrt(n) * 1.4) }, gLinks);
  links[key] = { p, from, to, n, used: 0, color, len: 0 };
}
camps.forEach(c => {
  c.graph.s2t.forEach(e => { const s = S.find(x => x.id === e.s); addLink('s:' + e.s, 't:' + e.t, e.n, s ? st(s)[0] : '#8a889c'); });
  c.graph.t2o.forEach(e => addLink('t:' + e.t, 'o:' + e.o, e.n, '#6250d6'));
});
Object.values(links).forEach(l => { try { l.len = l.p.getTotalLength(); } catch (e) { l.len = 0; } });

// ---- campaign state
function apply(c, first) {
  cur = c; const g = c.graph;
  document.querySelectorAll('.camp').forEach(b => b.classList.toggle('on', b.dataset.id === c.id));
  Object.values(links).forEach(l => l.used = 0);
  g.s2t.forEach(e => { const l = links['s:' + e.s + '>t:' + e.t]; if (l) l.used = e.used; });
  g.t2o.forEach(e => { const l = links['t:' + e.t + '>o:' + e.o]; if (l) l.used = e.used; });
  Object.values(links).forEach(l => { l.p.classList.toggle('hot', l.used > 0); l.p.classList.toggle('cold', !l.used); });
  g.sources.forEach(s => { const n = nodes['s:' + s.id]; if (n) { n.data = s; n.count.textContent = s.facts ? `${s.used}/${s.facts} facts` : ''; } });
  g.topics.forEach(t => { const n = nodes['t:' + t.id]; if (!n) return; n.data = t;
    tween(n.count, t.used, x => `${Math.round(x)} / ${t.facts}`, first ? 700 : 500);
    n.fill.setAttribute('width', t.facts ? (KW - 76) * t.used / t.facts : 0); });
  const feeding = {}; g.t2o.forEach(e => feeding[e.o] = (feeding[e.o] || 0) + e.used);
  O.forEach(o => { const n = nodes['o:' + o.id]; n.count.textContent = feeding[o.id] ? `${feeding[o.id]} facts feed it` : 'nothing feeds it for this campaign'; });
  document.getElementById('head').innerHTML =
    `<b id="hn">0</b> <span class="muted">of</span> ${g.total} facts used for ${esc(c.emoji)} ${esc(c.title)} <span class="muted">· the rest stay in the layer</span>`;
  tween(document.getElementById('hn'), g.used, x => Math.round(x), 700);
  pSub.textContent = `${g.total} facts filed by topic · ${g.used} relevant to ${c.audience_short || c.title}`;
  spawn(); if (pinned) trace(pinned); fit();
}
const cbox = document.getElementById('camps');
camps.forEach(c => { const b = document.createElement('button'); b.className = 'camp'; b.dataset.id = c.id;
  b.innerHTML = `${esc(c.emoji)} ${esc(c.title)}`; b.onclick = () => apply(c); cbox.appendChild(b); });

// ---- particles (light: capped, paused when hidden)
let pts = [];
function spawn() {
  gPts.innerHTML = ''; pts = []; if (reduce) return;
  const hot = Object.values(links).filter(l => l.used > 0 && l.len > 0);
  let budget = 90;
  hot.sort((a, b) => b.used - a.used).forEach(l => {
    const k = Math.min(3, Math.ceil(Math.sqrt(l.used))); for (let j = 0; j < k && budget > 0; j++, budget--) {
      const c = el('circle', { r: 2.6, fill: l.color, class: 'pt', opacity: .9 }, gPts);
      pts.push({ c, l, t: Math.random(), v: .18 + Math.random() * .12 }); } });
}
let last = performance.now();
function loop(now) {
  const dt = Math.min(.05, (now - last) / 1000); last = now;
  if (!document.hidden) for (const p of pts) {
    p.t = (p.t + dt * p.v * (220 / Math.max(120, p.l.len))) % 1;
    const q = p.l.p.getPointAtLength(p.t * p.l.len); p.c.setAttribute('cx', q.x); p.c.setAttribute('cy', q.y);
    p.c.style.opacity = p.l.p.classList.contains('dim') ? .06 : .9;
  }
  requestAnimationFrame(loop);
}
if (!reduce) requestAnimationFrame(loop);

// ---- tracing
let pinned = null;
function related(id) {
  const set = new Set([id]); const L = Object.values(links);
  const down = x => L.filter(l => l.from === x).forEach(l => { if (!set.has(l.to)) { set.add(l.to); down(l.to); } });
  const up = x => L.filter(l => l.to === x).forEach(l => { if (!set.has(l.from)) { set.add(l.from); up(l.from); } });
  if (id[0] === 's') down(id); else if (id[0] === 'o') up(id);
  else { down(id); up(id); }
  return set;
}
function trace(id) {
  const set = related(id);
  Object.entries(nodes).forEach(([k, n]) => { n.g.classList.toggle('dim', !set.has(k)); n.g.classList.toggle('focus', k === id); });
  Object.values(links).forEach(l => { const on = set.has(l.from) && set.has(l.to);
    l.p.classList.toggle('dim', !on); l.p.classList.toggle('trace', on && l.used > 0); });
}
function clear() { Object.values(nodes).forEach(n => n.g.classList.remove('dim', 'focus'));
  Object.values(links).forEach(l => l.p.classList.remove('dim', 'trace')); }
function tipHtml(id) {
  const n = nodes[id], d = n.data;
  if (n.kind === 's') { const [col, word] = st(d);
    const tl = (d.topics || []).map(t => { const x = T.find(y => y.id === t); return x ? `${x.icon} ${esc(x.label)}` : esc(t); }).join(', ');
    return `<h4>${esc(d.name)}</h4><div class="muted">${esc(d.provider)} · <b style="color:${col}">${word.toLowerCase()}</b> · confidence ${d.score || 0}/100</div>
      <div style="margin-top:5px">${esc(d.what)}</div>
      <div style="margin-top:5px">${d.facts ? `<b>${d.used}</b> of ${d.facts} facts used for ${esc(cur.title)}` : 'No facts yet: not connected'}${tl ? `<br>Files into: ${tl}` : ''}</div>
      ${d.example ? `<div class="ex">e.g. ${esc(d.example)}</div>` : ''}`; }
  if (n.kind === 't') { const ups = cur.graph.s2t.filter(e => e.t === d.id).map(e => { const s = S.find(x => x.id === e.s); return s ? esc(s.name) : esc(e.s); });
    const outs = cur.graph.t2o.filter(e => e.t === d.id && e.used).map(e => { const o = O.find(x => x.id === e.o); return o ? esc(o.label) : esc(e.o); });
    return `<h4>${esc(d.icon)} ${esc(d.label)}</h4><div><b>${d.used}</b> of ${d.facts} facts relevant to ${esc(cur.title)}</div>
      <div class="muted" style="margin-top:4px">From: ${ups.join(', ') || '—'}</div><div class="muted">Feeds: ${outs.join(', ') || 'nothing for this campaign'}</div>`; }
  const ins = cur.graph.t2o.filter(e => e.o === d.id && e.used).map(e => { const t = T.find(x => x.id === e.t); return `${t ? esc(t.label) : esc(e.t)} (${e.used})`; });
  return `<h4>${esc(d.icon)} ${esc(d.label)}</h4><div>Built from: ${ins.join(', ') || 'no facts for this campaign'}</div>`;
}
function showTip(id, ev) {
  tip.innerHTML = tipHtml(id); tip.classList.add('show');
  const r = document.body.getBoundingClientRect(), w = 320;
  let x = ev.clientX - r.left + 16; if (x + w > r.width) x = ev.clientX - r.left - w - 16;
  tip.style.left = Math.max(4, x) + 'px'; tip.style.top = (ev.clientY - r.top + 12) + 'px';
}
Object.entries(nodes).forEach(([id, n]) => {
  n.g.addEventListener('mouseenter', ev => { if (!pinned) trace(id); showTip(id, ev); });
  n.g.addEventListener('mousemove', ev => showTip(id, ev));
  n.g.addEventListener('mouseleave', () => { tip.classList.remove('show'); if (!pinned) clear(); });
  n.g.addEventListener('click', ev => { ev.stopPropagation(); pinned = pinned === id ? null : id; pinned ? trace(pinned) : clear(); });
});
svg.addEventListener('click', () => { pinned = null; clear(); });

apply(cur, true);
"""


def flow_html(data: dict) -> str:
    """Self-contained HTML for ``streamlit.components.v1.html`` (auto-fits its iframe)."""
    return _doc(_CSS, _BODY, _JS, data)
