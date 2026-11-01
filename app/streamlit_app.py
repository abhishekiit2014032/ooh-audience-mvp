"""OOH Audience Intelligence: Streamlit dashboard for placements H1 to H4.

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import io
import sys
import html
from datetime import date
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import pydeck as pdk  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from pyproj import Transformer  # noqa: E402

from ooh import duplication  # noqa: E402
from ooh import exec_ui  # noqa: E402
from ooh import footprint as footprint_mod  # noqa: E402
from ooh import flow_viz  # noqa: E402
from ooh import knowledge as knowledge_mod  # noqa: E402
from ooh import profile as profile_mod  # noqa: E402
from ooh import narrative as narrative_mod  # noqa: E402
from ooh import signals as signals_mod  # noqa: E402
from ooh import sources as sources_mod  # noqa: E402
from ooh.brain_viz import diagram_data  # noqa: E402
from ooh.activation import PLATFORM_MIN_RADIUS_KM  # noqa: E402
from ooh.config import (AssumptionConfig, Params, RoadClass, env_key, load_assumptions,  # noqa: E402
                        load_placements)
from ooh.geometry import cone_polygon_lonlat  # noqa: E402
from ooh.metrics import Metric, fmt_num  # noqa: E402
from ooh.pipeline import Results, compute, prepare, stress_test  # noqa: E402

st.set_page_config(page_title="OOH Decision Room", page_icon="📍", layout="wide")

# The app has two parts. Insights: what each location delivers, following the AI Solution Brief
# (location mapping, data, audience, compare, performance). Plan a campaign: the planning tools.
MAIN_PAGES = ["Locations", "Data sources", "Audience profile", "Compare locations", "Campaign performance"]
PLAN_PAGES = ["The brief", "Overview", "Explore a location", "Score & compare", "Decision", "Duplication and plan",
              "Campaign health"]
CHECK_PAGES = ["Map", "Placement detail", "Check the data", "Stress-test the pick", "Hand off", "Assumptions and sources"]
SECTIONS = {"Insights": MAIN_PAGES, "Plan a campaign": PLAN_PAGES + CHECK_PAGES}
SECTION_ICONS = {"Insights": "📊", "Plan a campaign": "🧭"}
PAGES = MAIN_PAGES + PLAN_PAGES + CHECK_PAGES


def section_of(page: str) -> str:
    return next((s for s, pages in SECTIONS.items() if page in pages), "Insights")


PAGE_ICONS = {"Locations": "📍", "Audience profile": "👥", "Compare locations": "⚖️", "Campaign performance": "📈", "The brief": "📋", "Overview": "🗺️", "Explore a location": "🔎", "Score & compare": "🏆", "Decision": "🎯",
              "Campaign health": "📈", "Data sources": "🧠", "Map": "🛰️", "Placement detail": "🔎", "Duplication and plan": "🔁", "Check the data": "🔍", "Stress-test the pick": "🧪", "Hand off": "📦",
              "Assumptions and sources": "📚"}
MAIN_SLIDERS = ["utilisation", "occupancy", "monthly_frequency", "cone_radius_m", "half_angle_deg",
                "interest_share", "obstruction_factor"]
BADGE_COLORS = {
    "VERIFIED": ("#0f5132", "#d1e7dd"),
    "ESTIMATE": ("#084298", "#cfe2ff"),
    "ASSUMPTION": ("#664d03", "#fff3cd"),
    "SAMPLE": ("#842029", "#f8d7da"),
    "CONCEPT": ("#41464b", "#e2e3e5"),
}
PLOT_LAYOUT = dict(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                   margin=dict(l=10, r=10, t=70, b=10), font=dict(size=13, color="#1d1b2e"),
                   title=dict(x=0, xanchor="left", y=0.98, yanchor="top"))
LEGEND_TOP = dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right")
SERIES = exec_ui.FACE_COLORS
_to_wgs = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)


# --------------------------------------------------------------------------- data


@st.cache_resource(show_spinner="Loading OpenStreetMap data and cutting road segments...")
def get_preps():
    pcfg = load_placements()
    params = Params(load_assumptions())
    return prepare(pcfg, params, allow_download=True)


def build_cfg(road_rows: tuple) -> AssumptionConfig:
    cfg = load_assumptions()
    if road_rows:
        cfg = cfg.model_copy(update={"road_classes": {
            name: RoadClass(lanes=int(l), utilisation_factor=float(u), speed_kmh=float(s))
            for name, l, u, s in road_rows}})
    return cfg


def ledger_stamp() -> str:
    """Changes whenever the event ledger or the manual events file changes (part of the cache key)."""
    parts = []
    for path in (signals_mod.LEDGER_PATH, signals_mod.MANUAL_EVENTS_PATH):
        parts.append(str(path.stat().st_mtime_ns) if path.exists() else "-")
    return "|".join(parts)


@st.cache_resource(max_entries=24, show_spinner="Recomputing...")
def get_results(overrides: tuple, road_rows: tuple, event_overrides: tuple = (), stamp: str = "",
                campaign_id: str | None = None) -> Results:
    pcfg = load_placements().with_campaign(campaign_id)
    params = Params(build_cfg(road_rows), dict(overrides))
    return compute(get_preps(), pcfg, params, event_overrides=dict(event_overrides))


EVENT_LABELS = {"full_closure": "Full closure", "partial_closure": "Partial closure", "roadworks": "Roadworks",
                "major_event": "Major event"}
STATUS_COLORS = {"applied": "#36B37E", "pending": "#F5A524", "rejected": "#6b7280"}


def event_hours(ev: dict, params: Params) -> str:
    et = params.cfg.event_types.get(ev["type"])
    s_, e_ = ev.get("start_hour"), ev.get("end_hour")
    if s_ is None and et:
        return f"{et.default_start_hour:02d}:00–{et.default_end_hour:02d}:00 (default, ASSUMPTION)"
    return f"{s_:02d}:00–{e_:02d}:00" if s_ is not None and e_ is not None else "unknown"


def event_faces(ev: dict, pcfg) -> str:
    types = load_assumptions().event_types
    return ", ".join(p.label for p in pcfg.placements if signals_mod.affects(ev, p, types)) or "none"


MOTION_CSS = """
<style>
:root { --ooh-accent:#6250d6; --ooh-soft:#f6f5fc; --ooh-line:#ecebf3; --ooh-ink:#1d1b2e; --ooh-muted:#8a889c; }
[data-testid="stMain"] .block-container { padding-top: 2.2rem; max-width: 1280px; }
@keyframes oohFadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes oohPulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(12,163,12,.45); } 70% { box-shadow: 0 0 0 7px rgba(12,163,12,0); } }
[data-testid="stMain"] [data-testid="stElementContainer"],
[data-testid="stMain"] [data-testid="stExpander"] { animation: oohFadeUp .35s cubic-bezier(.2,.8,.2,1) both; }
.ooh-card { background:#fff; transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
            box-shadow: 0 1px 2px rgba(29,27,46,.05); }
.ooh-card:hover { transform: translateY(-3px); box-shadow: 0 12px 28px rgba(98,80,214,.14); border-color: #6250d6 !important; }
.ooh-live { display:inline-block; width:8px; height:8px; border-radius:50%; background:#0ca30c; margin-right:6px;
            animation: oohPulse 1.8s infinite; vertical-align: middle; }
/* page header */
.ooh-head { margin: 0 0 14px; }
.ooh-eyebrow { display:inline-block; font-size:12.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
               color:var(--ooh-accent); background:#efedfc; border-radius:999px; padding:4px 12px; }
.ooh-title { font-size: 2.1rem !important; font-weight: 800 !important; letter-spacing: -.02em; margin: 10px 0 4px !important;
             padding: 0 !important; line-height: 1.15 !important; color: var(--ooh-ink); }
.ooh-sub { color: #55536a; font-size: 1.02rem; margin: 0; max-width: 780px; }
.ooh-analyst { display:inline-block; font-size:11.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
               color:#55536a; background:#f6f5fc; border:1px solid #ecebf3; border-radius:999px; padding:3px 10px; margin-bottom:4px; }
/* campaign + location context bar */
.ooh-ctx { background: linear-gradient(135deg, #f4f2ff, #ffffff); border: 1px solid #e4e0fb; border-radius: 14px;
           padding: 8px 14px; font-size: .9rem; color: var(--ooh-ink); line-height: 1.45; }
.ooh-ctx span { color: #55536a; font-size: .85rem; }
/* main pages: estimate steps, labels, compare table */
.est { display:flex; flex-direction:column; gap:6px; }
.est-row { display:grid; grid-template-columns:78px 1fr; gap:10px; align-items:start; padding:9px 12px;
           border:1px solid #ecebf3; border-radius:12px; background:#fff; }
.est-n { font-size:1.35rem; font-weight:800; letter-spacing:-.02em; color: var(--ooh-ink); }
.est-t { font-size:.86rem; color:#3d3b52; line-height:1.4; } .est-t b { color: var(--ooh-ink); }
.est-t span { color:#55536a; } .est-t .est-src { color:#8a889c; font-size:.78rem; }
.lbl { display:inline-block; font-size:10.5px; font-weight:700; border-radius:999px; padding:1px 8px; margin-left:4px;
       border:1px solid #ecebf3; background:#f7f6fc; color:#55536a; vertical-align:1px; }
.lbl.good { background:#e9f7e9; color:#0a7d0a; border-color:#cdeccd; }
.lbl.accent { background:#efedfc; color:#6250d6; border-color:#dcd7fb; }
.lbl.warn { background:#fff6e0; color:#8a5a00; border-color:#fbe3a6; }
.lbl.crit { background:#fdeaea; color:#a42a2a; border-color:#f6caca; }
[data-testid="stBaseButton-tertiary"] { min-height: 0; padding: 0; }
[data-testid="stBaseButton-tertiary"] p { font-size: .82rem; color: #55536a; }
[data-testid="stBaseButton-tertiary"]:hover p { color: #6250d6; }
a.jump { display:inline-block; font-size:.85rem; color:#6250d6; margin:0 0 6px; text-decoration:none; }
.nt-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px; }
.nt-grid4 { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; }
@media (max-width: 900px) { .nt-grid4 { grid-template-columns:1fr 1fr; } }
.nt { background:#fff; border:1px solid #ebe9f5; border-radius:12px; padding:12px 14px; }
.nt-t { font-size:.8rem; color:#55536a; } .nt-v { font-size:1.55rem; font-weight:800; letter-spacing:-.02em;
  color:var(--ooh-ink); line-height:1.25; } .nt-s { font-size:.78rem; color:#8a889c; }
.dots { color:#6250d6; letter-spacing:2px; font-size:1rem; }
.nt-v .dots { font-size:1.3rem; }
.sc { border-left:3px solid #6250d6; background:#faf9ff; padding:10px 14px; margin:6px 0 10px; font-size:.88rem; color:#3d3b52; }
.sc-h { font-size:.95rem; color:var(--ooh-ink); margin-bottom:4px; } .sc-d { margin:2px 0 6px; }
.sc-q { font-style:italic; color:#55536a; margin:4px 0 6px; }
.sc-src { margin-top:4px; } .sc-src span { color:#8a889c; font-size:.8rem; }
.pf-h { font-weight:700; color:var(--ooh-ink); margin-bottom:6px; }
.pf-n { font-size:.78rem; color:#8a889c; margin-top:6px; }
.pb { display:flex; align-items:center; gap:8px; font-size:.86rem; margin:4px 0; }
.pb-l { width:118px; color:#55536a; flex:none; } .pb-v { min-width:44px; text-align:right; color:var(--ooh-ink); font-weight:600; }
.pb-t { flex:1; height:8px; background:#f1f0f6; border-radius:4px; overflow:hidden; }
.pb-b { display:block; height:8px; background:#6250d6; border-radius:4px; }
.win { background:#f3fbf3; border:1px solid #cdeccd; border-radius:12px; padding:10px 14px; font-size:.88rem; color:#3d3b52; margin:8px 0; }
.win-h { font-weight:700; color:#0a7d0a; margin-bottom:4px; }
table.cmp2 td:nth-child(2), table.cmp2 td:nth-child(3), table.cmp2 th:nth-child(2), table.cmp2 th:nth-child(3) { text-align:center; width:24%; }
table.cmp2 tr.sec td { background:#f7f6fc; font-size:.75rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#8a889c; text-align:left; }
.src-tag { display:block; font-size:.72rem; color:#8a889c; }
table.cmp-t { width:100%; border-collapse:separate; border-spacing:0; font-size:.92rem; background:#fff;
              border:1px solid #ecebf3; border-radius:14px; overflow:hidden; }
table.cmp-t th { text-align:right; padding:10px 14px; font-size:.8rem; color:#55536a; background:#f7f6fc;
                 border-bottom:1px solid #ecebf3; }
table.cmp-t td { text-align:right; padding:9px 14px; border-bottom:1px solid #f1f0f6; font-variant-numeric:tabular-nums; }
table.cmp-t td:first-child, table.cmp-t th:first-child { text-align:left; color:#3d3b52; }
table.cmp-t tr:last-child td { border-bottom:none; }
table.cmp-t td.best { color:#0a7d0a; font-weight:800; background:#f3fbf3; }
/* the brief: question cards */
.q-eb { font-size: 11.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #8a889c; }
.q-q { font-size: .95rem; color: #55536a; margin: 2px 0 6px; line-height: 1.4; min-height: 2.6em; }
.q-a { font-size: 1.55rem; font-weight: 800; letter-spacing: -.02em; color: var(--ooh-ink); line-height: 1.2; }
.q-t { font-size: .9rem; color: #3d3b52; margin: 6px 0 10px; line-height: 1.5; min-height: 4.4em; }
.q-chip { display: inline-block; font-size: 11.5px; font-weight: 600; border-radius: 999px; padding: 3px 10px;
          border: 1px solid #ecebf3; background: #f7f6fc; color: #55536a; }
.q-chip.accent { background: #efedfc; color: #6250d6; border-color: #dcd7fb; }
.q-chip.warn { background: #fff6e0; color: #8a5a00; border-color: #fbe3a6; }
.q-chip.good { background: #e9f7e9; color: #0a7d0a; border-color: #cdeccd; }
/* sidebar navigation */
[data-testid="stSidebar"] { border-right: 1px solid var(--ooh-line); }
.ooh-brand { display:flex; align-items:center; gap:10px; margin: 0 0 14px; }
.ooh-brand .logo { width:38px; height:38px; border-radius:12px; display:grid; place-items:center; font-size:20px;
                   background: linear-gradient(135deg, #8b7cf0, #6250d6); box-shadow: 0 6px 16px rgba(98,80,214,.3); }
.ooh-brand b { font-size: 1.05rem; color: var(--ooh-ink); display:block; line-height:1.2; }
.ooh-brand span { font-size: .8rem; color: var(--ooh-muted); }
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] { gap: 2px; padding-top: 4px; position: relative; width: 100%; }
[data-testid="stSidebar"] [data-testid="stButtonGroup"] button { padding: 8px 10px; border-radius: 10px; }
[data-testid="stSidebar"] [data-testid="stButtonGroup"] button p { font-size: .95rem; font-weight: 700; white-space: nowrap; }
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] > div { width: 100%; position: relative; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] { width: 100%; padding: 7px 10px; border-radius: 10px; margin: 0;
    cursor: pointer; transition: background .15s ease, transform .15s ease; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:not([data-testid="stMarkdownContainer"]) { display: none; }
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover { background: #efedfc; transform: translateX(3px); }
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] > div[data-selected="true"] [data-testid="stRadioOption"] {
    background: #efedfc; box-shadow: inset 3px 0 0 #6250d6; }
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] > div[data-selected="true"] p { font-weight: 700; color: #6250d6; }
[data-testid="stSidebar"] [data-testid="stRadio"] p { font-size: .95rem; }
/* overview: section titles and location cards */
.ooh-sec { font-size: 1.25rem; font-weight: 800; color: var(--ooh-ink); letter-spacing: -.01em; margin: 26px 0 2px; }
.ooh-mini { font-size: .85rem; color: #55536a; margin: 0 0 6px; }
.ooh-loc { font-size: .95rem; color: var(--ooh-ink); line-height: 1.4; }
.ooh-loc .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align: middle; }
.ooh-star { font-size: .72rem; font-weight: 700; color: #6250d6; background: #efedfc; border-radius: 999px; padding: 1px 8px;
            margin-left: 4px; }
.ooh-locsub { font-size: .8rem; color: var(--ooh-muted); margin: 2px 0 4px; }
.ooh-locnum { font-size: .85rem; color: #55536a; }
/* tidy containers */
[data-testid="stPlotlyChart"], [data-testid="stDeckGlJsonChart"] { border-radius: 14px; overflow: hidden; }
[data-testid="stPlotlyChart"] { border: 1px solid var(--ooh-line); padding: 6px 8px; background:#fff; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
[data-testid="stExpander"] details { border-radius: 12px; }
iframe { border: 0; }
@media (prefers-reduced-motion: reduce) {
  [data-testid="stMain"] [data-testid="stElementContainer"], [data-testid="stMain"] [data-testid="stExpander"],
  .ooh-live { animation: none; }
  .ooh-card, .ooh-card:hover { transition: none; transform: none; }
}
</style>
"""


# --------------------------------------------------------------------------- UI helpers


def kpi_strip(items: list[tuple[str, float, str, str]]) -> None:
    """Headline numbers that settle into place (count up from 85 % of the value). (title, value, unit, label)"""
    import json as _json

    data = _json.dumps([{"t": t, "v": v, "u": u, "l": l, "c": BADGE_COLORS.get(l, ("#41464b", "#e2e3e5"))}
                        for t, v, u, l in items])
    components.html(f"""
<div id="k" style="display:grid;grid-template-columns:repeat({len(items)},1fr);gap:12px;
     font-family:system-ui,-apple-system,sans-serif;color:#1d1b2e"></div>
<script>
const D = {data}; const root = document.getElementById('k');
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
function fmt(x) {{ const a = Math.abs(x); if (a >= 1e6) return (x/1e6).toFixed(2) + 'M';
  if (a >= 1e4) return (x/1e3).toFixed(1) + 'k'; return Math.round(x).toLocaleString(); }}
D.forEach((d, i) => {{
  const c = document.createElement('div');
  c.style.cssText = 'background:linear-gradient(160deg,#ffffff,#f7f6fc);border:1px solid #ecebf3;border-radius:14px;' +
    'padding:12px 14px;transition:transform .18s,border-color .18s;opacity:0;transform:translateY(6px)';
  c.onmouseenter = () => {{ c.style.transform = 'translateY(-3px)'; c.style.borderColor = '#6250d6'; }};
  c.onmouseleave = () => {{ c.style.transform = 'none'; c.style.borderColor = '#ecebf3'; }};
  c.innerHTML = `<div style="font-size:12.5px;color:#55536a">${{d.t}}
     <span style="background:${{d.c[1]}};color:${{d.c[0]}};border-radius:4px;padding:0 5px;font-size:10px;font-weight:700;margin-left:4px">${{d.l}}</span></div>
     <div style="font-size:30px;font-weight:700;line-height:1.25"><span class="n">0</span>
     <span style="font-size:13px;font-weight:400;color:#8a889c">${{d.u}}</span></div>`;
  root.appendChild(c);
  setTimeout(() => {{ c.style.transition = 'opacity .35s, transform .35s, border-color .18s';
                     c.style.opacity = 1; c.style.transform = 'none'; }}, 40 + i * 70);
  const n = c.querySelector('.n'), start = reduce ? d.v : d.v * 0.85, t0 = performance.now(), T = 700;
  function step(t) {{ const k = Math.min(1, (t - t0) / T), e = 1 - Math.pow(1 - k, 3);
    n.textContent = fmt(start + (d.v - start) * e); if (k < 1) requestAnimationFrame(step); }}
  requestAnimationFrame(step);
}});
</script>""", height=96)


def badge(label: str) -> str:
    fg, bg = BADGE_COLORS.get(label, ("#41464b", "#e2e3e5"))
    return (f"<span style='background:{bg};color:{fg};border-radius:4px;padding:1px 6px;"
            f"font-size:0.72rem;font-weight:600;letter-spacing:0.03em'>{label}</span>")


def v_color(v: float, vmax: float) -> list[int]:
    """Light blue (low visibility) to deep navy (high): one-hue sequential ramp for a light basemap."""
    t = 0.0 if vmax <= 0 else min(1.0, v / vmax)
    stops = [(0.0, (134, 182, 239)), (0.35, (57, 135, 229)), (0.7, (37, 106, 191)), (1.0, (13, 54, 107))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return [int(c0[i] + k * (c1[i] - c0[i])) for i in range(3)] + [235]
    return [13, 54, 107, 235]


def metric_card(title: str, m: Metric, unit: str = "", pct: bool = False) -> None:
    f = (lambda v: f"{v:.0%}") if pct else fmt_num
    st.markdown(
        f"<div class='ooh-card' style='border:1px solid rgba(128,128,128,0.35);border-radius:8px;padding:10px 12px;"
        f"margin-bottom:8px'>"
        f"<div style='font-size:0.8rem;opacity:0.75'>{title} {badge(m.label)}</div>"
        f"<div style='font-size:1.6rem;font-weight:650;line-height:1.3'>{f(m.value)}"
        f"<span style='font-size:0.8rem;font-weight:400;opacity:0.7'> {unit}</span></div>"
        f"<div style='font-size:0.78rem;opacity:0.8'>low {f(m.low)} · high {f(m.high)}</div>"
        f"<div style='font-size:0.72rem;opacity:0.6'>{m.source}</div></div>",
        unsafe_allow_html=True)


def label_line(text: str, label: str) -> None:
    st.markdown(f"{text} {badge(label)}", unsafe_allow_html=True)


def lonlat_path(geom) -> list[list[float]]:
    xs, ys = geom.xy
    lon, lat = _to_wgs.transform(np.asarray(xs), np.asarray(ys))
    return [[float(a), float(b)] for a, b in zip(lon, lat)]


# --------------------------------------------------------------------------- sidebar

_RG = '[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] > div'
_GROUP_LABEL = ("{rg}:nth-of-type({n}) {{ margin-top: 30px; }} {rg}:nth-of-type({n})::before {{ content: '{t}'; "
                "position:absolute; top:-20px; left:10px; font-size: 11px; font-weight: 800; letter-spacing: .1em; "
                "color: var(--ooh-muted); }}")
SECTION_CSS = {
    "Insights": f"<style>{_RG} p {{ font-size: 1rem; font-weight: 600; }}</style>",
    "Plan a campaign": "<style>" + _GROUP_LABEL.format(rg=_RG, n=1, t="PLAN")
    + _GROUP_LABEL.format(rg=_RG, n=len(PLAN_PAGES) + 1, t="CHECK AND HAND OFF") + "</style>",
}


def sidebar(acfg: AssumptionConfig, pcfg) -> tuple[str, dict, tuple, bool]:
    st.sidebar.markdown(
        f"<div class='ooh-brand'><div class='logo'>📍</div><div><b>OOH Decision Room</b>"
        f"<span>Outdoor billboards · Dubai</span></div></div>", unsafe_allow_html=True)
    # Two parts: a switch picks the part, and only that part's pages are listed.
    if st.session_state.get("section") not in SECTIONS:
        st.session_state["section"] = section_of(st.session_state.get("page", MAIN_PAGES[0]))
    section = st.sidebar.segmented_control("Part of the app", list(SECTIONS), key="section", required=True,
                                           label_visibility="collapsed", width="stretch",
                                           format_func=lambda x: f"{SECTION_ICONS[x]} {x}")
    pages = SECTIONS[section]
    if st.session_state.get("page") not in pages:
        st.session_state["page"] = pages[0]
    st.sidebar.markdown(SECTION_CSS[section], unsafe_allow_html=True)
    page = st.sidebar.radio("Page", pages, key="page", label_visibility="collapsed",
                            format_func=lambda x: f"{PAGE_ICONS.get(x, '')}\u2002{x}")
    # The interest-share slider starts from the active campaign's target share, and follows a campaign switch.
    camp = pcfg.campaign
    camp_share = float(camp.interest_share if camp.interest_share is not None else
                       acfg.parameters["interest_share"].value)
    camp_tilt = float(camp.fit_tilt if camp.fit_tilt is not None else acfg.parameters["fit_tilt"].value)
    if st.session_state.get("_slider_campaign") != camp.id:
        st.session_state["param_interest_share"] = camp_share
        st.session_state["param_fit_tilt"] = camp_tilt
        st.session_state["_slider_campaign"] = camp.id

    st.sidebar.divider()
    st.sidebar.caption("🎛️ ANALYST CONTROLS · every number in the app follows these")
    overrides: dict[str, float] = {}

    def control(key: str, container) -> None:
        p = acfg.parameters[key]
        skey = f"param_{key}"
        if skey not in st.session_state:
            st.session_state[skey] = float(p.value)
        if p.min == p.max:
            container.caption(f"{key}: {p.value:g} {p.unit} (fixed)")
            return
        value = container.slider(f"{key.replace('_', ' ').capitalize()} ({p.unit})", float(p.min),
                                 float(p.max), step=float(p.step), key=skey, help=p.description)
        if key in ("interest_share", "fit_tilt") or abs(value - p.value) > 1e-12:
            overrides[key] = float(value)

    with st.sidebar.expander("Key assumptions"):
        if st.button("↺ Reset all assumptions", width="stretch"):
            for key in list(st.session_state.keys()):
                if key.startswith("param_") or key == "road_editor":
                    del st.session_state[key]
            st.rerun()
        for key in MAIN_SLIDERS:
            control(key, st)

    with st.sidebar.expander("All other assumptions"):
        groups: dict[str, list[str]] = {}
        for key, p in acfg.parameters.items():
            if key not in MAIN_SLIDERS:
                groups.setdefault(p.group, []).append(key)
        for group, keys in groups.items():
            st.markdown(f"**{group}**")
            for key in keys:
                control(key, st)

    with st.sidebar.expander("Road classes (lanes, utilisation, speed)"):
        base_df = pd.DataFrame([{"class": k, "lanes": v.lanes, "utilisation_factor": v.utilisation_factor,
                                 "speed_kmh": v.speed_kmh} for k, v in acfg.road_classes.items()])
        edited = st.data_editor(base_df, key="road_editor", hide_index=True, disabled=["class"],
                                width="stretch")
        road_rows = tuple((r["class"], r["lanes"], r["utilisation_factor"], r["speed_kmh"])
                          for r in edited.to_dict(orient="records"))
        if edited.equals(base_df):
            road_rows = ()

    with st.sidebar.expander("AI and data connections"):
        has_claude = env_key("ANTHROPIC_API_KEY") is not None
        use_llm = st.toggle("Claude narratives", value=False, disabled=not has_claude,
                            help="Needs ANTHROPIC_API_KEY. Off by default: each new set of numbers is one "
                                 "API call (cached on disk). Without it a template writes the narrative.")
        keys = {k: env_key(k) is not None for k in ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "MAPILLARY_TOKEN",
                                                   "ANTHROPIC_API_KEY"]}
        st.caption("API keys: " + ", ".join(f"{k.split('_')[0].title()} {'set' if v else 'not set'}"
                                            for k, v in keys.items()))
    changed = [k for k in overrides if k != "interest_share" or abs(overrides[k] - camp_share) > 1e-12]
    if changed or road_rows:
        st.sidebar.warning(f"{len(changed) + (1 if road_rows else 0)} assumption(s) changed from the defaults.")
    return page, overrides, road_rows, use_llm


# --------------------------------------------------------------------------- pages


# --------------------------------------------------------------------------- executive pages


def html_block(doc: str, height: int) -> None:
    """Render a self-contained HTML block; it grows to fit its content after load."""
    components.html(doc, height=height, scrolling=False)


def page_header(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(exec_ui.header_html(eyebrow, title, subtitle), unsafe_allow_html=True)


def analyst_tag() -> None:
    st.markdown("<span class='ooh-analyst'>🧰 Analyst toolkit · full technical detail</span>",
                unsafe_allow_html=True)


def trust_of(*labels: str) -> list[str]:
    order = ["VERIFIED", "ESTIMATE", "ASSUMPTION", "SAMPLE", "CONCEPT"]
    worst = max(labels, key=lambda l: order.index(l) if l in order else 1)
    return list(exec_ui.TRUST.get(worst, ("Estimate", "")))


def cap(text: str) -> str:
    """Capitalise the first letter only (keeps "SUV")."""
    return text[:1].upper() + text[1:]


def road_short(corridor: str) -> str:
    return corridor.replace(" Road", " Rd")


def name_of(res: Results, pid: str) -> str:
    return res.placements[pid].prep.placement.label


def face_rows(res: Results, focus: str | None = None) -> list[dict]:
    """One row per billboard, in config order, with the numbers the executive pages use.

    No prices are used anywhere. Price level is our 1-4 rating (config/placements.yaml) and value is
    the target audience per price level, relative to the best board, also shown as a rating.
    """
    plan_ids = {s.placement for s in res.plan}
    rows = []
    for i, (pid, r) in enumerate(res.placements.items()):
        p, rr = r.prep.placement, r.profile.relevant_reach
        rows.append({"id": pid, "label": p.label, "name": p.name, "road": road_short(p.corridor),
                     "area_full": p.area, "type": p.type.title(), "price_level": int(p.price_level),
                     "rel": float(rr.value), "rel_lo": float(rr.low), "rel_hi": float(rr.high),
                     "unique": float(r.metrics["unique_month"].value),
                     "color": exec_ui.FACE_COLORS[i % len(exec_ui.FACE_COLORS)], "in_plan": pid in plan_ids,
                     "label_trust": rr.label, "sov": float(p.share_of_voice), "focus": pid == focus})
    per_level = {f["id"]: f["rel"] / f["price_level"] for f in rows}
    best = max(per_level.values()) or 1.0
    by_level = sorted(rows, key=lambda f: (f["price_level"], f["id"]))
    for f in rows:
        f["value"] = round(per_level[f["id"]] / best * 100)
        f["value_dots"] = knowledge_mod.rating_level(f["value"] / 100)
        f["price_rank"] = by_level.index(f) + 1                               # 1 = lowest price level
        f["price_dots"] = f["price_level"]
    return rows


def plan_options(res: Results, boards: int) -> dict:
    """De-duplicated reach for every mix of billboards, and the plan builder's pick for each number of boards."""
    items, mat = res.plan_items, res.overlap
    uniques = duplication.uniques_dict(items)
    ids = [it.id for it in items]
    subsets = {}
    for k in range(1, len(ids) + 1):
        for combo in combinations(ids, k):
            subsets[",".join(sorted(combo))] = {
                "rel": float(duplication.combined_relevant(list(combo), items, mat)),
                "all": float(duplication.combined_unique(list(combo), uniques, mat))}
    picks = {str(k): [s.placement for s in duplication.best_plan(items, mat, k)] for k in range(1, len(ids) + 1)}
    return {"subsets": subsets, "picks": picks, "n_max": len(ids), "boards": int(boards)}


def news_events(res: Results, params: Params) -> list[dict]:
    """Switched-on road events that move at least one billboard's forecast, with their effect per face.

    ``delta`` is in views of our ad (placement impressions × share of voice), matching the delivery figures.
    """
    by_id = {e["id"]: e for e in res.events}
    hits: dict[str, dict] = {}
    for pid, f in res.forecasts.items():
        sov = float(res.placements[pid].prep.placement.share_of_voice)
        for h in f.applied:
            ev = hits.setdefault(h["event"], {"faces": {}})
            face = ev["faces"].setdefault(pid, {"delta": 0.0, "day_change": h["change"], "campaign": 0.0})
            face["delta"] += float(h["impressions_delta"]) * sov
            face["campaign"] = face["delta"] / (f.baseline.value * sov) if f.baseline.value and sov else 0.0
            face["day_change"] = min(face["day_change"], h["change"])
    out = []
    for eid, hit in hits.items():
        e = by_id.get(eid, {"type": "event", "date": eid.split("|")[-1]})
        d = date.fromisoformat(str(e["date"])[:10])
        out.append({"id": eid, "date": d, "type": EVENT_LABELS.get(e["type"], e["type"]),
                    "note": e.get("note") or e.get("corridor") or "",
                    "where": e.get("stretch") or e.get("corridor") or ", ".join(e.get("areas", [])),
                    "hours": event_hours(e, params) if "type" in e else "", "confidence": e.get("confidence"),
                    "faces": hit["faces"], "source": e.get("source", "")})
    return sorted(out, key=lambda x: x["date"])


def delivery_summary(res: Results) -> pd.DataFrame:
    g = res.delivery.groupby("placement").agg(planned=("planned", "sum"), forecast=("forecast", "sum"),
                                              actual=("actual", "sum"))
    g["index"] = g["actual"] / g["planned"]
    g["news"] = g["forecast"] / g["planned"] - 1
    return g


def context_bar(pcfg) -> tuple:
    """Campaign and location pickers, folded into one small button at the top right: open it to change them."""
    camps = pcfg.campaign_options()
    by_id = {c.id: c for c in camps}
    ids = [p.id for p in pcfg.placements]
    short = {p.id: p.label for p in pcfg.placements}
    labels = {p.id: f"{p.label} · {road_short(p.corridor)}" for p in pcfg.placements}
    cid_now = st.session_state.get("campaign_id") if st.session_state.get("campaign_id") in by_id else camps[0].id
    pid_now = st.session_state.get("pid") if st.session_state.get("pid") in short else ids[0]
    _, right = st.columns([4, 1.4])
    with right.popover(f"{by_id[cid_now].emoji} {by_id[cid_now].title} · {short[pid_now]}", width="stretch",
                       help="Change the campaign or the location"):
        cid = st.selectbox("Campaign", [c.id for c in camps], key="campaign_id",
                           format_func=lambda i: f"{by_id[i].emoji} {by_id[i].title}")
        pid = st.selectbox("Location", ids, key="pid", format_func=lambda i: labels[i])
        c = by_id[cid]
        st.caption(f"{c.plan_start:%d %b} – {c.plan_end:%d %b %Y} · {c.boards} boards · "
                   f"target audience: {c.audience}")
    return by_id[cid], pid


def page_decision(res: Results, pcfg, params: Params, focus: str) -> None:
    c = pcfg.campaign
    faces = face_rows(res, focus)
    opts = plan_options(res, c.boards)
    trust = trust_of(*[f["label_trust"] for f in faces])
    page_header(f"{c.emoji} {c.title} · {c.plan_start:%B %Y}",
                f"Which billboards should carry our {c.title}?",
                f"We compared {len(faces)} billboards on how many <b>{c.audience}</b> each one reaches, counting every "
                f"driver once. Here is the best mix of {c.boards} boards. Tap the cards to try your own.")
    html_block(exec_ui.decision_html({"faces": faces, "trust": trust, "aud_short": c.audience_short, **opts}),
               height=560)

    plan_ids = [s.placement for s in res.plan]
    deliv = delivery_summary(res)
    scope = [i for i in plan_ids if i in deliv.index] or list(deliv.index)
    d = deliv.loc[scope]
    expected = float(d["actual"].sum() / d["planned"].sum()) if d["planned"].sum() else 1.0
    status = ("Looks on track", "good") if expected >= 0.97 else ("Keep an eye on it", "warn") if expected >= 0.9 else \
        ("Likely behind plan", "crit")
    light = [name_of(res, pid) for pid, r in d.iterrows() if r["index"] < 0.97]
    started = date.today() > c.plan_start
    events = news_events(res, params)
    plan_rel = [f for f in faces if f["in_plan"]] or faces
    lo_x = sum(f["rel_lo"] for f in plan_rel) / sum(f["rel"] for f in plan_rel)
    hi_x = sum(f["rel_hi"] for f in plan_rel) / sum(f["rel"] for f in plan_rel)
    meter = {"VERIFIED": 5, "ESTIMATE": 3, "ASSUMPTION": 2, "SAMPLE": 2, "CONCEPT": 1}
    worst = min((f["label_trust"] for f in faces), key=lambda l: meter.get(l, 3))
    tiles = [
        {"emoji": "📦", "q": "Will it deliver?", "a": f"{expected:.0%}", "unit": "of planned views expected",
         "text": ((f"For our pick ({', '.join(name_of(res, i) for i in scope)}), " if plan_ids else "Across all billboards, ")
                  + ("based on a simulated month: no media-owner play logs or live traffic counts are connected yet. "
                     if not started else "simulated until play logs and live counts are connected. ")
                  + (f"{', '.join(light)} may run a little light." if light else "Every board is at or above plan.")),
         "chips": [(f"{'✅' if status[1] == 'good' else '👀' if status[1] == 'warn' else '🔴'} {status[0]}", status[1]),
                   ("Simulated", "warn")]},
    ]
    hits_plan = [(e, {k: v for k, v in e["faces"].items() if k in plan_ids}) for e in events]
    hits_plan = [(e, f) for e, f in hits_plan if f]
    others = sorted({name_of(res, k) for e in events for k in e["faces"] if k not in plan_ids})
    if hits_plan:
        e, fs = hits_plan[0]
        wid, wv = min(fs.items(), key=lambda kv: kv[1]["delta"])
        small = abs(wv["campaign"]) < 0.02
        tiles.append({"emoji": "🚧", "q": "Anything in the way?",
                      "a": f"{len(hits_plan)} road event{'s' if len(hits_plan) > 1 else ''}", "unit": "for our pick",
                      "text": (f"<b>{e['date']:%a %d %b}</b>: {e['note'] or e['type']}. {name_of(res, wid)} loses about "
                               f"{exec_ui.people(abs(wv['delta']))} views of our ad that day "
                               f"({wv['campaign']:+.1%} over the month)."),
                      "chips": [("Small effect" if small else "Material effect", "good" if small else "warn"),
                                ("From news headlines", "accent")]})
    else:
        tiles.append({"emoji": "🌤️", "q": "Anything in the way?", "a": "All clear", "unit": "for our pick",
                      "text": ("No closures, roadworks or big events are expected near the boards we recommend "
                               "during the campaign."
                               + (f" The only one found affects {', '.join(others)}, which is not in our pick."
                                  if others else "")),
                      "chips": [("From news headlines", "accent")]})
    pulse, crowd_plan, _ = crowd_pulse(res, pcfg, params)
    near_pick = [(pid, e) for pid in plan_ids for e in pulse[pid].events]
    near_all = [(pid, e) for pid, lp in pulse.items() for e in lp.events]
    same = [s.placement for s in crowd_plan] == plan_ids
    if near_all:
        pid, top = max(near_pick or near_all, key=lambda pe: pe[1].extra_people)
        extra = sum(e.extra_people for _, e in near_pick)
        what = html.escape(top.group.what)
        tiles.append({"emoji": "📣", "q": "Crowds nearby?",
                      "a": f"+{exec_ui.people(extra)}" if near_pick else f"{len(near_all)} event{'s' if len(near_all) > 1 else ''}",
                      "unit": "people on event days" if near_pick else "near other boards",
                      "text": (f"<b>{what}</b> ({top.group.event_start:%d %b}) "
                               f"{'brought' if (top.group.event_end or top.group.event_start) <= date.today() else 'brings'} about "
                               f"{exec_ui.people(top.extra_people)} extra people past {name_of(res, pid)}"
                               + ("" if near_pick else ", which is not in our pick")
                               + (". Small next to everyday traffic, so the pick stays the same."
                                  if same else ". Counting it would change our pick: see What's on nearby.")),
                      "chips": [("Same pick" if same else "Pick changes", "good" if same else "warn"),
                                ("Sourced numbers", "accent")]})
    else:
        tiles.append({"emoji": "📣", "q": "Crowds nearby?", "a": "Quiet", "unit": "month",
                      "text": "No event with a published crowd figure is found near our billboards during the campaign.",
                      "chips": [("Sourced numbers", "accent")]})
    tiles.append({"emoji": "🔍", "q": "How sure are we?", "a": trust[0], "unit": "", "meter": meter.get(worst, 3),
                  "text": (f"Good for ranking the billboards; treat head counts as a range. The audience could land "
                           f"between {lo_x:.1f}× and {hi_x:.1f}× our central figure, mostly depending on how often the "
                           "same people repeat the trip. Traffic is estimated from road capacity, not live counters."),
                  "chips": [("Ranking: reliable", "good"), ("Head counts: wide range", "warn")]})

    why = None
    left_out = [f for f in faces if f["id"] not in plan_ids]
    if plan_ids and left_out:
        f = max(left_out, key=lambda x: x["rel"])
        best = max(faces, key=lambda x: x["value"])
        key_plan, key_with = ",".join(sorted(plan_ids)), ",".join(sorted(plan_ids + [f["id"]]))
        inc = opts["subsets"][key_with]["rel"] - opts["subsets"][key_plan]["rel"]
        base_rel = opts["subsets"][key_plan]["rel"]
        points = []
        if f["value"] <= min(x["value"] for x in faces):
            points.append(f"<b>Lowest value:</b> {f['label']} reaches the fewest {c.audience_short} for its "
                          f"price level ({knowledge_mod.rating(f['value_dots'])} against "
                          f"{knowledge_mod.rating(best['value_dots'])} for {best['label']}).")
        else:
            points.append(f"<b>Value:</b> {knowledge_mod.rating(f['value_dots'])} audience for its price level.")
        mat = res.overlap
        partner = max(plan_ids, key=lambda x: mat.loc[f["id"], x] / min(mat.loc[f["id"], f["id"]], mat.loc[x, x]))
        share = mat.loc[f["id"], partner] / min(mat.loc[f["id"], f["id"]], mat.loc[partner, partner])
        rule = str(res.overlap_rules.loc[f["id"], partner])
        smaller = partner if mat.loc[partner, partner] <= mat.loc[f["id"], f["id"]] else f["id"]
        other = f["id"] if smaller == partner else partner
        if share >= 0.2:
            points.append(f"<b>Same drivers:</b> about {share:.0%} of the people who pass {name_of(res, smaller)} also "
                          f"pass {name_of(res, other)}"
                          f"{' (same road, same direction)' if 'same corridor' in rule else ''}, so much of its "
                          "audience is already covered.")
        points.append(f"<b>Small gain:</b> as one more board it would add only "
                      f"{exec_ui.people(inc)} more {c.audience_short} (+{inc / base_rel:.0%}); the brief books "
                      f"{c.boards} boards.")
        why = {"title": f"Why isn't {f['label']} ({f['road']}) in the plan?", "points": points}
    html_block(exec_ui.insights_html({"tiles": tiles, "why": why}), height=520)
    st.caption(f"Head counts are people per month, counted once even if they pass several times. "
               f"\"{cap(c.audience_short)}\" = {c.audience}. Price level and value are our 1-4 ratings "
               "comparing the billboards with each other; no prices are used. "
               "Full method in the Analyst toolkit.")


def audience_payload(res: Results, pcfg, focus: str, only: str | None = None) -> dict:
    c = pcfg.campaign
    faces = [f for f in face_rows(res, focus) if only is None or f["id"] == only]
    out = []
    for f in sorted(faces, key=lambda x: (not x["in_plan"], -x["rel"])):
        r = res.placements[f["id"]]
        prof, meta = r.profile, r.profile.meta
        age = meta.get("age", {})
        male = float(meta.get("gender", {}).get("male", 0.5))
        core = sum(v for k, v in age.items() if k in ("25-34", "35-44", "45-54"))
        premium = any("premium" in s for s in prof.segments.get("Demographic", []))
        place_cat, place_words = profile_mod.CATEGORY_PLACES[profile_mod.category_key(c.brand_category)]
        near = int(prof.poi_counts.get(place_cat, 0))
        top_poi = [k.lower() for k, v in sorted(prof.poi_counts.items(), key=lambda kv: -kv[1])[:2] if v]
        hourly = [float(x) for x in r.reach.scenarios["base"].hourly_impressions]
        rush = sum(hourly[7:10] + hourly[17:20]) / sum(hourly) if sum(hourly) else 0
        share = prof.interest_share.value
        tenths = round(core * 10)
        slots = round(1 / f["sov"]) if f["sov"] else 1
        if f["type"] == "Digital":
            sowhat = (f"<b>So what:</b> this is a digital screen, so we can choose when to run. Weight the creative to the "
                      f"7–10 am and 5–8 pm rush, when {rush:.0%} of views happen. Our ad shares the screen with "
                      f"{slots - 1} others, so keep it simple.")
        else:
            sowhat = ("<b>So what:</b> a static board shows one message all day to drivers at motorway speed, "
                      "so design for a two-second glance.")
        if c.creative_hint:
            sowhat += f" <b>For our {c.title}:</b> {c.creative_hint}"
        if near >= 10:
            sowhat += f" With {near} {place_words} within 1 km, a 'find us nearby' call to action fits."
        target = [["🎯", exec_ui.people(f["rel"]), f"{c.audience_short} a month"],
                  ["🧩", f"{share:.0%}" if share < 1 else "Everyone", f"of passers-by match the campaign"],
                  ["🏬", f"{near}", f"{place_words} within 1 km"],
                  ["📺", f"1 in {slots}" if slots > 1 else "All day", "screen time is ours" if slots > 1
                   else "our ad is always on show"]]
        out.append({
            "id": f["id"], "label": f["label"], "color": f["color"], "in_plan": f["in_plan"],
            "avatar": "💼" if premium else "🚙",
            "headline": f"{'Premium-area' if premium else 'Everyday'} commuters on {f['road']} at {f['label']}",
            "blurb": (f"{tenths} in 10 are aged 25–54 and {male:.0%} are men. Nearly all of them pass by road"
                      f"{', plus a few metro riders' if r.reach.metro else ''}. "
                      + (f"Around the board you mostly find {' and '.join(top_poi)}." if top_poi else "")),
            "general": [["👥", exec_ui.people(f["unique"]), "different people pass every month"],
                        ["🎂", f"{tenths} in 10", "aged 25–54"],
                        ["👨", f"{male:.0%}", "men"],
                        ["⏰", f"{rush:.0%}", "of views in the two rush hours"]],
            "target": target, "hourly": hourly,
            "age": {k.replace("-", "–"): float(v) for k, v in age.items()}, "male": male, "sowhat": sowhat})
    return {"faces": out, "focus": focus, "audience": c.audience, "emoji": c.emoji, "campaign": c.title}


def page_audience(res: Results, pcfg, focus: str, only: str | None = None) -> None:
    if only is None:
        page_header("👥 Audience", "Who will see our ad, and when?",
                    "First everyone who drives past, then the slice our campaign is after. "
                    "Use it to brief the creative and, on digital screens, to schedule it. ⭐ = in our plan.")
    html_block(exec_ui.audience_html(audience_payload(res, pcfg, focus, only)), height=900)
    faces = face_rows(res, focus)
    label = "SAMPLE" if any(res.placements[f["id"]].profile.meta_is_sample for f in faces) else "ESTIMATE"
    st.caption(f"Age, gender and interests come from Meta audience estimates ({exec_ui.TRUST[label][0].lower()}: "
               f"{exec_ui.TRUST[label][1].lower()}). The hourly shape is a standard Dubai commuter curve (assumption). "
               "Nearby places are from OpenStreetMap.")


def crowd_pulse(res: Results, pcfg, params: Params) -> tuple[dict, list, list]:
    """Crowd events per billboard for the selected campaign, the crowd-adjusted plan, and all fact groups."""
    facts = footprint_mod.all_facts(pcfg)
    pulse = footprint_mod.pulse_for_results(res, pcfg, pcfg.campaign, params, facts)
    plan, _ = footprint_mod.plan_with_crowds(res, pulse, pcfg.campaign.boards)
    return pulse, plan, footprint_mod.group_facts(facts)


def _fact_view(g, campaign, in_window: bool = False) -> dict:
    """What the page needs to show one sourced number (escaped in the browser)."""
    year = g.figure_year or (g.event_start.year if g.event_start and not in_window else None)
    rng = f"{exec_ui.people(g.low)}–{exec_ui.people(g.high)}" if g.high > g.low * 1.02 else ""
    return {"what": g.what, "icon": g.icon, "value": g.value, "unit": g.unit, "period": g.period,
            "year": year, "old": bool(year and year < date.today().year - 2), "measure": g.measure,
            "match": bool(set(g.tags) & set(campaign.news_tags)), "note": g.note,
            "sources": g.sources, "sources_n": len(g.sources), "range": rng}


def page_news(res: Results, pcfg, params: Params, focus: str, embedded: bool = False) -> None:
    c = pcfg.campaign
    faces = face_rows(res, focus)
    pulse, crowd_plan, groups = crowd_pulse(res, pcfg, params)
    if not embedded:
        page_header(f"📣 What's on nearby · {c.plan_start:%B %Y}",
                    "What does the news say about crowds at our locations?",
                    f"Sourced numbers from news and official pages: big events during the {c.title}, and the "
                    f"visitors, residents and metro riders that make each spot busy. <b>{cap(c.audience_short)}</b> "
                    "crowds are shown first. ⭐ = in our plan.")
    out = []
    for f in faces:
        lp = pulse[f["id"]]
        evs = []
        for e in lp.events:
            g = e.group
            evs.append({**_fact_view(g, c, in_window=True),
                        "start": g.event_start.isoformat(), "end": (g.event_end or g.event_start).isoformat(),
                        "visitors": e.visitors_in_window, "extra": e.extra_people, "target": e.extra_target,
                        "match": e.matches_campaign, "capped": e.capped})
        later = sorted((_fact_view(g, c) for g in lp.later), key=lambda x: (not x["match"], -x["value"]))
        context = sorted((_fact_view(g, c) for g in lp.context),
                         key=lambda x: (x["measure"] == "capacity", x["old"], -x["value"]))
        out.append({"id": f["id"], "label": f["label"], "color": f["color"], "in_plan": f["in_plan"],
                    "events": evs, "later": later, "context": context,
                    "n_facts": len(lp.events) + len(lp.later) + len(lp.context)})
    tracked = {pid for g in groups for pid in g.placements}
    away = []
    for g in groups:
        if g.placements or not (set(g.tags) & set(c.news_tags)) or g.kind != "event_attendance":
            continue
        in_win = bool(g.event_start and g.event_start <= c.plan_end and (g.event_end or g.event_start) >= c.plan_start)
        when = (f"{g.event_start:%d %b}" if g.event_start else (f"{g.figure_year} figure" if g.figure_year else ""))
        away.append({"what": g.what, "icon": g.icon, "value": g.value, "when": when, "in_window": in_win,
                     "quote": g.sources[0]["quote"], "title": g.sources[0]["title"]})
    away.sort(key=lambda x: (not x["in_window"], -x["value"]))

    all_events = [(f, e) for f in out for e in f["events"]]
    extra = sum(lp.extra_people for lp in pulse.values())
    target = sum(lp.extra_target for lp in pulse.values())
    days = (c.plan_end - c.plan_start).days + 1
    everyday = sum(float(r.metrics["people_day"].value) for r in res.placements.values()) * days
    before, after = [s.placement for s in res.plan], [s.placement for s in crowd_plan]
    types = params.cfg.event_types
    closures = [ev for ev in res.events if ev.get("type") == "full_closure"
                and st.session_state.get("event_overrides", {}).get(ev["id"], ev.get("enabled", False))]

    def closed(pid: str, e: dict) -> bool:
        p = res.placements[pid].prep.placement
        return any(signals_mod.affects(ev, p, types) and ev["date"] <= e["end"] and ev["end_date"] >= e["start"]
                   for ev in closures)

    ahead = [(f, e) for f, e in all_events
             if date.fromisoformat(e["end"]) > date.today() and not closed(f["id"], e)]
    best = max(ahead, key=lambda fe: (fe[0]["in_plan"], fe[1]["extra"]), default=None)
    best_txt = ""
    if best:
        f, e = best
        d0 = date.fromisoformat(e["start"])
        best_txt = f"the biggest crowd still ahead is {d0:%a %d %b} at {f['label']} ({e['what']})"
        if f["in_plan"] and res.placements[f["id"]].prep.placement.type == "digital":
            best_txt += ", a digital screen in our pick, so we can weight our slots to it"
        elif not f["in_plan"]:
            best_txt += ", a board outside our pick"
    summary = {"n_events": len(all_events), "n_car": sum(1 for _, e in all_events if e["match"]),
               "extra": extra, "target": target, "n_facts": sum(f["n_facts"] for f in out),
               "ratio": f"{float(f'{everyday / extra:.2g}'):,.0f}" if extra else "", "changed": before != after,
               "before": ", ".join(name_of(res, i) for i in before) or "none",
               "after": ", ".join(name_of(res, i) for i in after) or "none", "best": best_txt}
    data = {"faces": out, "focus": focus, "summary": summary, "away": away, "emoji": c.emoji,
            "audience_short": c.audience_short, "window": f"{c.plan_start:%d %b} – {c.plan_end:%d %b %Y}",
            "start": c.plan_start.isoformat(), "days": days,
            "pass_share": round(params.base("news_event_pass_share") * 100)}
    html_block(exec_ui.pulse_html(data), height=1100)
    store = footprint_mod.PeopleStore.load()
    st.caption(f"Numbers are quoted from the linked pages as found by AI web search: kept only when the quote states "
               f"the number and the link was a real search result (open a link to check; source quality varies). A crowd becomes extra people passing our board "
               f"with our assumptions: {params.base('news_event_pass_share'):.0%} of visitors pass a nearby board, "
               f"capped at {params.base('event_max_daily_change'):.0%} of a normal day; "
               f"{params.base('news_audience_match_share'):.0%} of a matching event's visitors (e.g. a motor show, "
               f"property show or shopping festival, by tag) count as "
               f"{c.audience_short}. Visitor, resident and ridership numbers are shown as evidence, not added to reach. "
               f"Last search: {store.updated_at[:10] or 'never'} · {len(tracked)} of {len(faces)} locations have "
               "sourced numbers. Analysts can review every number under Check the data.")


# --------------------------------------------------------------------------- knowledge layer pages


@st.cache_data(show_spinner=False)
def source_names() -> dict:
    return {x.id: x.name for x in sources_mod.registry()}


def knowledge_facts(res: Results, pcfg, params: Params) -> list:
    return knowledge_mod.build(res, pcfg, params)


def goto(page: str | None = None, focus: str | None = None, campaign: str | None = None) -> None:
    """Switch page / location / campaign from a button or a map click (applied before the widgets are built)."""
    if campaign:
        st.session_state["_campaign"] = campaign
    if page:
        st.session_state["_goto"] = page
    if focus:
        st.session_state["_focus"] = focus
    st.rerun()


def apply_pending() -> None:
    if "_goto" in st.session_state:
        st.session_state["page"] = st.session_state.pop("_goto")
        st.session_state["section"] = section_of(st.session_state["page"])
    if "_focus" in st.session_state:
        st.session_state["pid"] = st.session_state.pop("_focus")
    if "_campaign" in st.session_state:
        st.session_state["campaign_id"] = st.session_state.pop("_campaign")


def flow_payload(res: Results, pcfg, params: Params) -> dict:
    """Data-flow diagram for every campaign, so the campaign chips switch it instantly."""
    reg = sources_mod.registry()
    facts = knowledge_facts(res, pcfg, params)
    graphs = []
    for c in pcfg.campaign_options():
        g = knowledge_mod.flow_graph(facts, c, reg)
        graphs.append({"id": c.id, "title": c.title, "emoji": c.emoji, "audience_short": c.audience_short, "graph": g})
    data = dict(next(g["graph"] for g in graphs if g["id"] == pcfg.campaign.id))
    data["campaigns"] = graphs
    data["focus_campaign"] = pcfg.campaign.id
    return data


def page_overview(res: Results, pcfg, params: Params, focus: str) -> None:
    c = pcfg.campaign
    plan_ids = [s.placement for s in res.plan]
    page_header("📍 OOH Decision Room · Dubai",
                f"{len(res.placements)} billboards, {len(pcfg.campaign_options())} campaigns (cars, property, retail): where should each run?",
                "Every source feeds one knowledge layer; each campaign reads only what it needs from it. "
                "Click a billboard on the map (or a card) to explore it.")
    facts = knowledge_facts(res, pcfg, params)
    pulse = footprint_mod.pulse_for_results(res, pcfg, c, params)
    scores = knowledge_mod.score_locations(res, pcfg, c, facts, pulse)
    order = sorted(scores["total"], key=lambda k: -scores["total"][k])
    faces = {f["id"]: f for f in face_rows(res, focus)}

    col_map, col_cards = st.columns([2.15, 1], gap="medium")
    with col_map:
        close = st.segmented_control(
            "Map view", ["🌍 All locations", f"🔍 Close-up: {res.placements[focus].prep.placement.label}"],
            default="🌍 All locations", key="overview_zoom", label_visibility="collapsed") != "🌍 All locations"
        radius, half = params.base("cone_radius_m"), params.base("half_angle_deg")
        seg_rows, cone_rows, pin_rows = [], [], []
        vmax = max((float(r.scored["V"].max()) for r in res.placements.values() if not r.scored.empty), default=1)
        for pid, r in res.placements.items():
            s, p, f = r.prep.snapped, r.prep.placement, faces[pid]
            rgb = [int(f["color"][i:i + 2], 16) for i in (1, 3, 5)]
            flows = r.reach.scenarios["base"].flows.set_index("flow") if len(r.reach.scenarios["base"].flows) else None
            if not r.scored.empty:
                for row in r.scored[r.scored["included"]].itertuples():
                    vol = flows.loc[row.flow, "vehicles_day"] if flows is not None and row.flow in flows.index else 0
                    seg_rows.append({"path": lonlat_path(row.geometry), "color": v_color(row.V, vmax),
                                     "tooltip": (f"<b>{html.escape(p.label)}</b> · road in view: {html.escape(str(row.label))}"
                                                 f"<br/>{exec_ui.people(vol)} vehicles a day on this road")})
            alpha = 70 if pid == focus else 40
            cone_rows.append({"polygon": cone_polygon_lonlat(s.lon, s.lat, s.facing_bearing_deg, radius, half),
                              "fill": rgb + [alpha], "line": rgb + [200],
                              "tooltip": f"<b>{html.escape(p.label)}</b>: where the board can be seen (up to {radius:.0f} m)"})
            rank = order.index(pid) + 1
            pin_rows.append({"position": [s.lon, s.lat], "label": f"#{rank} {p.label}",
                             "pid": pid, "color": rgb + [255], "r": (18 if close else 90 if pid == focus else 55),
                             "tooltip": (f"<b>{html.escape(p.label)}</b> · {road_short(p.corridor)}<br/>"
                                         f"{p.type.title()} board · {exec_ui.people(r.metrics['unique_month'].value)} "
                                         f"people a month<br/>{exec_ui.people(r.profile.relevant_reach.value)} "
                                         f"{html.escape(c.audience_short)} · #{rank} for the {html.escape(c.title)}"
                                         f"{'<br/>⭐ in our plan' if pid in plan_ids else ''}<br/><i>Click to explore</i>")})
        layers = [
            pdk.Layer("PolygonLayer", cone_rows, id="cones", get_polygon="polygon", get_fill_color="fill",
                      get_line_color="line", line_width_min_pixels=1, pickable=True),
            pdk.Layer("PathLayer", seg_rows, id="roads", get_path="path", get_color="color", width_min_pixels=3,
                      pickable=True),
            pdk.Layer("ScatterplotLayer", [x for x in pin_rows if x["pid"] == focus], id="focus_ring",
                      get_position="position", get_radius=45 if close else 260, get_fill_color=[98, 80, 214, 30],
                      get_line_color=[98, 80, 214, 200], line_width_min_pixels=2, stroked=True,
                      radius_min_pixels=14 if close else 18),
            pdk.Layer("ScatterplotLayer", pin_rows, id="pins", get_position="position", get_radius="r",
                      get_fill_color="color", get_line_color=[255, 255, 255], line_width_min_pixels=3, stroked=True,
                      radius_min_pixels=8, pickable=True),
            pdk.Layer("TextLayer", pin_rows, id="labels", get_position="position", get_text="label", get_size=14,
                      get_color=[29, 27, 46], get_pixel_offset=[0, -24], font_weight=700,
                      outline_width=4, outline_color=[255, 255, 255, 255],
                      font_settings={"sdf": True}),
        ]
        lats = [r.prep.snapped.lat for r in res.placements.values()]
        lons = [r.prep.snapped.lon for r in res.placements.values()]
        fs = res.placements[focus].prep.snapped
        view = (pdk.ViewState(latitude=fs.lat, longitude=fs.lon, zoom=14.4, pitch=0) if close else
                pdk.ViewState(latitude=float(np.mean(lats)), longitude=float(np.mean(lons)), zoom=10.75, pitch=0))
        event = st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="light",
                                         tooltip={"html": "{tooltip}", "style": {"fontSize": "12.5px"}}),
                                height=520, on_select="rerun", selection_mode="single-object", key="overview_map")
        picked = (getattr(event, "selection", None) or {}).get("objects", {}) if event else {}
        # Act on a new click only: the map keeps its selection, so a later change of the location picker
        # must not snap the focus back to the last clicked pin.
        objs = picked.get("pins") or []
        sel = objs[0].get("pid") if objs else None
        if sel != st.session_state.get("_map_last"):
            st.session_state["_map_last"] = sel
            if sel and sel != focus:
                goto(focus=sel)
        st.caption("Coloured wedge = where a board can be seen; blue roads = the traffic that sees it (darker = "
                   "better view). Use the close-up (or zoom in) to see them. Basemap © CARTO, data © OpenStreetMap "
                   "contributors.")
    with col_cards:
        st.markdown(f"<div class='ooh-mini'>Ranked for the <b>{c.emoji} {c.title}</b></div>", unsafe_allow_html=True)
        for i, pid in enumerate(order):
            f = faces[pid]
            with st.container(border=True):
                st.markdown(
                    f"<div class='ooh-loc'><span class='dot' style='background:{f['color']}'></span>"
                    f"<b>{['🥇', '🥈', '🥉'][i] if i < 3 else '#' + str(i + 1)} {f['label']}</b>"
                    f"{' <span class=ooh-star>⭐ in plan</span>' if f['in_plan'] else ''}"
                    f"<div class='ooh-locsub'>{f['road']} · {f['type']} · score {knowledge_mod.score_int(scores['total'][pid])}</div>"
                    f"<div class='ooh-locnum'><b>{exec_ui.people(f['unique'])}</b> people / month · "
                    f"<b>{exec_ui.people(f['rel'])}</b> {c.audience_short}</div></div>", unsafe_allow_html=True)
                if st.button(f"Explore {f['label']} →", key=f"ov_{pid}", width="stretch",
                             type="primary" if pid == focus else "secondary"):
                    goto("Explore a location", pid)

    st.markdown("<div class='ooh-sec'>How we know: data sources → knowledge layer → outcomes</div>",
                unsafe_allow_html=True)
    st.caption("Each source files facts into the knowledge layer. Pick a campaign to see which facts it uses "
               "(particles) and which outcomes they shape. Hover any box to trace it.")
    html_block(flow_viz.flow_html(flow_payload(res, pcfg, params)), height=760)

    st.markdown("<div class='ooh-sec'>Next</div>", unsafe_allow_html=True)
    n1, n2, n3 = st.columns(3)
    if n1.button("📍 Explore a location", width="stretch"):
        goto("Explore a location")
    if n2.button("🏆 Score & compare", width="stretch"):
        goto("Score & compare")
    if n3.button("🎯 Build the plan", width="stretch", type="primary"):
        goto("Decision")


def page_explore(res: Results, pcfg, params: Params, focus: str, use_llm: bool = False) -> None:
    c = pcfg.campaign
    r = res.placements[focus]
    p = r.prep.placement
    faces = {f["id"]: f for f in face_rows(res, focus)}
    f = faces[focus]
    facts = knowledge_facts(res, pcfg, params)
    pulse = footprint_mod.pulse_for_results(res, pcfg, c, params)
    scores = knowledge_mod.score_locations(res, pcfg, c, facts, pulse)
    order = sorted(scores["total"], key=lambda k: -scores["total"][k])
    picks = knowledge_mod.select(facts, c, focus)
    by = {x.fact.id: x.fact for x in picks}
    page_header(f"📍 Explore a location · {c.emoji} {c.title}",
                f"What do we know about {p.label}, and what matters for the {c.title}?",
                "Pick another location or campaign at the top: the facts re-filter to what that campaign needs.")
    dwell = by.get(f"{focus}:dwell")
    base = r.reach.scenarios["base"]
    engage = [
        ["👥", exec_ui.people(f["unique"]), "different people a month", False],
        [c.emoji, exec_ui.people(f["rel"]), f"{c.audience_short} a month", True],
        ["⏱️", f"{dwell.value:.0f} s" if dwell else "–", "in view per pass (main road)", False],
        ["👁️", f"{r.metrics['mean_visibility'].value * 100:.0f}/100", "visibility score", False],
        ["⏰", f"{r.profile.commuter_share:.0%}", "of traffic in the rush hours", False],
        ["🚇", exec_ui.people(r.reach.metro.daily_riders) if r.reach.metro and base.metro_impressions_day else "–",
         "metro riders a day nearby", False],
    ]
    tags = []
    if f["value"] == 100:
        tags.append("💎 most audience for its price level")
    poi = r.profile.poi_counts
    place_cat, place_words = profile_mod.CATEGORY_PLACES[profile_mod.category_key(c.brand_category)]
    if poi.get(place_cat, 0) >= 20:
        tags.append(f"📍 {poi[place_cat]} {place_words} nearby")
    if by.get(f"{focus}:premium") and by[f"{focus}:premium"].value:
        tags.append("✨ premium area")
    n = len(order)
    srcs = {s for x in picks for s in x.fact.sources}
    data = {
        "loc": {"id": focus, "label": p.label, "road": p.corridor, "color": f["color"],
                "format": (f"Digital screen, our ad 1 in {round(1 / p.share_of_voice)}" if p.type == "digital"
                           and p.share_of_voice < 1 else f"{p.type.title()} board"),
                "size": f"{p.width_m:g} × {p.height_m:g} m",
                "price_word": by[f"{focus}:price"].display if f"{focus}:price" in by else "",
                "in_plan": f["in_plan"], "rank": order.index(focus) + 1, "n": n, "tags": tags},
        "campaign": {"title": c.title, "emoji": c.emoji, "audience_short": c.audience_short},
        "engage": engage,
        "counts": {"total": len(picks), "used": sum(1 for x in picks if x.used), "sources": len(srcs)},
        "topics": knowledge_mod.rules()["topics"],
        "facts": [{"title": x.fact.title, "display": x.fact.display, "topic": x.fact.topic, "reason": x.reason,
                   "score": round(x.score, 2), "used": x.used, "trust": x.fact.trust,
                   "sources": [source_names().get(s, s) for s in x.fact.sources], "url": x.fact.url,
                   "quote": x.fact.quote, "detail": x.fact.detail} for x in picks],
    }
    html_block(exec_ui.explore_html(data), height=900)
    view = st.segmented_control("Look closer", ["👥 Who passes", "📣 Crowds & news"], default="👥 Who passes",
                                key="explore_view")
    if view == "📣 Crowds & news":
        page_news(res, pcfg, params, focus, embedded=True)
    else:
        page_audience(res, pcfg, focus, only=focus)
    with st.expander(f"✍️ Who passes {p.label}, in a paragraph"):
        text, source = narrative_mod.narrative(r.facts, c.brand, use_llm=use_llm)
        st.markdown(f"<div style='border-left:3px solid {SERIES[0]};padding:6px 12px'>"
                    f"{text.replace(chr(10), '<br/>')}</div>", unsafe_allow_html=True)
        st.caption(f"Written by: {source}. Turn on *Claude narratives* under Analyst controls for a Claude version.")


def score_payload(res: Results, pcfg, params: Params, focus: str, across: dict | None = None) -> dict:
    c = pcfg.campaign
    facts = knowledge_facts(res, pcfg, params)
    pulse = footprint_mod.pulse_for_results(res, pcfg, c, params)
    sc = knowledge_mod.score_locations(res, pcfg, c, facts, pulse)
    R = knowledge_mod.rules()["criteria"]
    plan_ids = [s.placement for s in res.plan]
    faces = {f["id"]: f for f in face_rows(res, focus)}
    mat = res.overlap
    locs = []
    for pid, f in faces.items():
        why_out = ""
        if pid not in plan_ids and plan_ids:
            # overlap is in people; as a share of this board's own audience
            partner = max(plan_ids, key=lambda x: mat.loc[pid, x])
            share = mat.loc[pid, partner] / mat.loc[pid, pid] if mat.loc[pid, pid] else 0.0
            parts = []
            if share >= 0.2:
                parts.append(f"about {share:.0%} of its drivers also pass {faces[partner]['label']}, already in the plan")
            parts.append(f"the brief books {c.boards} boards and the other mix reaches more {c.audience_short}")
            if f["value"] < 100:
                parts.append(f"its value is {knowledge_mod.rating(f['value_dots'])} for its price level")
            why_out = "; ".join(parts) + "."
        locs.append({"id": pid, "label": f["label"], "road": f["road"], "color": f["color"], "in_plan": f["in_plan"],
                     "focus": pid == focus, "format": f["type"],
                     "scores": {k: {"score": v[pid]["score"], "why": v[pid]["why"]}
                                for k, v in sc["criteria"].items()}, "why_out": why_out})
    return {"criteria": [{"id": k, **R[k], "flat": k in sc["flat"]} for k in R],
            "weights": sc["weights"], "locs": locs, "focus": focus,
            "plan": [faces[i]["label"] for i in plan_ids],
            "campaign": {"id": c.id, "title": c.title, "emoji": c.emoji}, "across": across}


def page_score(res: Results, pcfg, params: Params, focus: str, okey: tuple, road_rows: tuple, ekey: tuple) -> None:
    c = pcfg.campaign
    page_header(f"🏆 Score & compare · {c.emoji} {c.title}",
                f"Which location fits the {c.title} best?",
                "Each location is scored 0–100 on five criteria, relative to the others, from the facts that matter "
                "for this campaign. Move the weights to test what you care about; click a row for the reasons.")
    pall = load_placements()
    across = {"locs": [{"id": p.id, "label": p.label} for p in pall.placements], "campaigns": []}
    for camp in pall.campaign_options():
        ov = dict(okey)
        ov["interest_share"] = camp.interest_share if camp.interest_share is not None else ov.get("interest_share", 0.3)
        r2 = res if camp.id == c.id else get_results(tuple(sorted(ov.items())), road_rows, ekey, ledger_stamp(), camp.id)
        p2 = pall.with_campaign(camp.id)
        f2 = knowledge_facts(r2, p2, params)
        pulse2 = footprint_mod.pulse_for_results(r2, p2, camp, params)
        s2 = knowledge_mod.score_locations(r2, p2, camp, f2, pulse2)
        across["campaigns"].append({"id": camp.id, "title": camp.title, "emoji": camp.emoji,
                                    "totals": {k: knowledge_mod.score_int(v) for k, v in s2["total"].items()},
                                    "plan": [s.placement for s in r2.plan]})
    html_block(exec_ui.score_html(score_payload(res, pcfg, params, focus, across)), height=880)
    st.caption("Scores compare our billboards with each other (best = 100 for audience, value and fit). Crowd timing "
               "earns 100 when sourced crowds add 5% to a board's month. Audience fit uses local signals from "
               "OpenStreetMap and the premium-area rule, chosen per industry (car showrooms for a car launch, premium "
               "and business districts for a property launch, malls and leisure for a retail festival). "
               + ("Fit counts twice on purpose for this campaign: it also tilts each board's share of the campaign "
                  f"audience (fit tilt {params.overrides.get('fit_tilt', 0):g}, an ASSUMPTION, until real Meta shares "
                  "per board arrive), so the plan follows fit too. " if params.overrides.get("fit_tilt", 0) > 0 else
                  "This campaign uses one flat audience share at every board (fit tilt 0, as in the solution brief), "
                  "so fit shows here but does not move the plan. ")
               + "Weights and signals are in config/knowledge.yaml.")


def page_health(res: Results, pcfg, params: Params, focus: str, header: bool = True) -> None:
    faces = face_rows(res, focus)
    c = pcfg.campaign
    if header:
        page_header("📈 Campaign health", "Is the campaign delivering what we paid for?",
                    f"{c.emoji} {c.title}, {c.plan_start:%d %b} – {c.plan_end:%d %b %Y}. Views of our ad against the "
                    "plan for each billboard (⭐ = in our pick), and anything on the roads that changes the forecast.")
    g = delivery_summary(res)
    rows = []
    for f in faces:
        if f["id"] not in g.index:
            continue
        r = g.loc[f["id"]]
        weeks = res.delivery[res.delivery["placement"] == f["id"]]["delivery_index"].astype(float).tolist()
        rows.append({"id": f["id"], "label": f["label"], "road": f["road"], "color": f["color"],
                     "index": float(r["index"]), "in_plan": f["in_plan"],
                     "planned": float(r["planned"]), "actual": float(r["actual"]), "news": float(r["news"]),
                     "news_views": float(r["forecast"] - r["planned"]), "weeks": weeks})
    events = []
    for e in news_events(res, params):
        chips = [(f"{name_of(res, pid)}: {v['day_change']:+.0%} that day · {exec_ui.people(abs(v['delta']))} views", "crit")
                 for pid, v in e["faces"].items()]
        if e.get("confidence"):
            chips.append((f"{e['confidence']:.0%} confident", ""))
        chips.append(("From news" if e["source"] != "manual" else "Added by planner", "accent"))
        hours = e["hours"].split(" (")[0] if e["hours"] else ""
        events.append({"mon": f"{e['date']:%b}".upper(), "day": e["date"].day, "wd": f"{e['date']:%a}",
                       "title": f"{e['type']}: {e['note']}" if e["note"] else e["type"],
                       "text": " · ".join(x for x in [e["where"], hours] if x), "chips": chips})
    total_p, total_a = float(g["planned"].sum()), float(g["actual"].sum())
    html_block(exec_ui.health_html({
        "overall": total_a / total_p if total_p else 1.0, "planned": total_p, "actual": total_a,
        "ok": 0.97, "watch": 0.90, "faces": rows, "events": events,
        "foot": ("📌 Delivered views are <b>simulated</b> until the media owner's play logs and live traffic counts are "
                 "connected. Road events come from news headlines, dated by AI and checked against sources; analysts "
                 "can switch each one on or off under Check the data. Views = views of our ad (our slot only).")}),
        height=640)


# --------------------------------------------------------------------------- analyst pages


def _people_tab(res: Results, pcfg, params: Params) -> None:
    c = pcfg.campaign
    st.markdown(
        "Claude searches the web for **numbers about people** at each location: event attendance, visitors to "
        "malls and attractions, new homes and offices, metro riders and traffic counts. A number is kept only "
        "when its quote states it and its link is a page the search really returned. Only dated crowd events "
        "inside the campaign window are turned into extra people passing a board (config shares); the rest is "
        "evidence. " + badge("ESTIMATE") + " quoted numbers (source quality varies: open the link) · "
        + badge("ASSUMPTION") + " pass share and audience match",
        unsafe_allow_html=True)
    store = footprint_mod.PeopleStore.load()
    c_btn, c_force, c_info = st.columns([1.3, 1, 2.2])
    force = c_force.toggle("Search again today", value=False, help="By default each location is searched once a day.")
    has_key = env_key("ANTHROPIC_API_KEY") is not None
    if c_btn.button("Search for people numbers", type="primary", width="stretch", disabled=not has_key,
                    help="One Claude web-search call per location plus one per campaign industry (cars, property, shopping); about 2 to 4 min."):
        with st.spinner("Searching news and official pages for people numbers..."):
            store = footprint_mod.refresh(pcfg, force=force)
        st.rerun()
    counts = store.counts()
    c_info.caption(f"Last search {store.updated_at[:16].replace('T', ' ') or 'never'} UTC · "
                   f"{counts.get('kept', 0)} kept · {counts.get('filtered', 0)} filtered out · "
                   + ("Claude web search" if has_key else "no Claude key: add facts in data/inputs/people_facts.yaml"))

    pulse, crowd_plan, _ = crowd_pulse(res, pcfg, params)
    st.subheader(f"Effect on the {c.title} ({c.plan_start:%d %b} – {c.plan_end:%d %b})")
    rows = [{"Face": name_of(res, pid), "Crowd events in window": len(lp.events),
             f"Of which {c.audience_short}": len(lp.match_events),
             "Extra people passing": lp.extra_people,
             f"Extra {c.audience_short}": lp.extra_target,
             "Share of a normal month": lp.extra_people / (res.placements[pid].metrics["people_day"].value
                                                           * ((c.plan_end - c.plan_start).days + 1) or 1),
             "Context numbers": len(lp.context) + len(lp.later)} for pid, lp in pulse.items()]
    st.dataframe(pd.DataFrame(rows).style.format({"Extra people passing": "{:,.0f}", f"Extra {c.audience_short}": "{:,.0f}",
                                                  "Share of a normal month": "{:.2%}"}),
                 hide_index=True, width="stretch")
    before = " → ".join(name_of(res, s.placement) for s in res.plan) or "none"
    after = " → ".join(name_of(res, s.placement) for s in crowd_plan) or "none"
    st.markdown(f"**Plan without crowds:** {before}  \n**Plan with crowds counted:** {after}"
                + ("  \n✅ Same pick." if before == after else "  \n🔀 The pick changes."))

    st.subheader("Every number found")
    show = st.segmented_control("Show", ["Kept", "Filtered out"], default="Kept", key="people_filter")
    want = "filtered" if show == "Filtered out" else "kept"
    facts = [f for f in footprint_mod.all_facts(pcfg, store) if f["status"] == want]
    if not facts:
        st.info("Nothing here yet. Press 'Search for people numbers', or add facts to data/inputs/people_facts.yaml.")
        return
    per = {"event": "", "hour": "/hour", "day": "/day", "week": "/week", "month": "/month", "year": "/year", "total": ""}
    df = pd.DataFrame([{
        "Use": bool(f.get("enabled", True)), "Kind": footprint_mod.KINDS[f["kind"]]["icon"] + " "
        + footprint_mod.KINDS[f["kind"]]["label"], "What": f["what"], "Place": f.get("place", ""),
        "Number": float(f["value"]), "Unit": f"{f.get('unit', '')}{per.get(f.get('period'), '')}",
        "When": (f"{f['event_start']} → {f.get('event_end') or f['event_start']}" if f.get("event_start")
                 else (f"{f['figure_year']} figure" if f.get("figure_year") else "")),
        "Measure": f.get("measure", "count"), "Tags": ", ".join(f.get("tags", [])),
        "Faces": ", ".join(name_of(res, i) for i in f.get("placements", []) if i in res.placements) or "elsewhere",
        "Quote": f.get("quote", ""), "Source": f.get("source_url", ""), "Note": f.get("note", ""),
        "Why filtered": f.get("reason", ""), "Confidence": float(f.get("confidence", 0)), "id": f["id"]}
        for f in sorted(facts, key=lambda f: (f["kind"], -float(f["value"])))])
    cols = [c_ for c_ in df.columns if c_ != "id" and (want == "filtered" or c_ != "Why filtered")]
    edited = st.data_editor(df, hide_index=True, width="stretch", key="people_editor", column_order=cols,
                            disabled=[c_ for c_ in df.columns if c_ != "Use"],
                            column_config={"Use": st.column_config.CheckboxColumn("Use", help="Switch a number off if it is wrong"),
                                           "Number": st.column_config.NumberColumn(format="%,.0f"),
                                           "Source": st.column_config.LinkColumn("Source", display_text="open ↗"),
                                           "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
    changed = {r["id"]: bool(r["Use"]) for r in edited.to_dict("records")
               if r["id"] in store.facts and bool(store.facts[r["id"]].get("enabled", True)) != bool(r["Use"])}
    if changed:
        for fid, on in changed.items():
            store.facts[fid]["enabled"] = on
        store.save()
        st.rerun()
    st.caption("Stored in data/signals/people.json (online) and data/inputs/people_facts.yaml (typed in by a planner; "
               "switch those off in the file). Sources are news sites and official pages found by Claude's web search; "
               "a commercial product needs licensed data.")


def _road_tab(res: Results, pcfg, params: Params) -> None:
    st.markdown(
        "Recent headlines for each corridor and area are collected, filtered for relevance and turned into "
        "**dated events** (closures, roadworks, major events). Switched-on events adjust the campaign forecast; "
        "the size of each effect comes from config, never from the AI. "
        + badge("VERIFIED") + " headlines as published · " + badge("ESTIMATE") + " event extraction · "
        + badge("ASSUMPTION") + " effect sizes", unsafe_allow_html=True)

    ledger = signals_mod.Ledger.load()
    c_btn, c_gdelt, c_info = st.columns([1.3, 1, 2.2])
    gdelt = c_gdelt.toggle("Include GDELT", value=False, help="Second news source; rate-limited on some networks.")
    has_key = env_key("ANTHROPIC_API_KEY") is not None
    if c_btn.button("Refresh signals", type="primary", width="stretch",
                    help="Fetch news, extract new events with Claude, look up missing dates and hours online."):
        with st.spinner("Collecting headlines, extracting events, checking sources (about 10 s to 2 min)..."):
            ledger = signals_mod.refresh(pcfg, params, use_gdelt=gdelt)
        st.rerun()
    c_info.caption(f"Ledger updated {ledger.updated_at[:16].replace('T', ' ') or 'never'} UTC · "
                   + ("Claude extracts events" if has_key else "no Claude key: articles stay pending"))

    counts = ledger.counts()
    cols = st.columns(4)
    tiles = [("Articles tracked", len(ledger.articles), "#4C9AFF"), ("Kept (in events)", counts.get("applied", 0), "#36B37E"),
             ("Pending (no date)", counts.get("pending", 0), "#F5A524"), ("Filtered out as noise", counts.get("rejected", 0), "#6b7280")]
    for col, (label, n, color) in zip(cols, tiles):
        col.markdown(f"<div class='ooh-card' style='border-left:3px solid {color};padding:6px 12px;border-radius:6px'>"
                     f"<div style='font-size:0.8rem;opacity:0.75'>{label}</div>"
                     f"<div style='font-size:1.7rem;font-weight:700'>{n}</div></div>", unsafe_allow_html=True)

    st.subheader("Events")
    events = sorted(signals_mod.active_events(ledger), key=lambda e: e["date"])
    if not events:
        st.info("No dated events yet. Press 'Refresh signals', or add a known closure to data/inputs/events.yaml.")
    else:
        overrides = st.session_state.get("event_overrides", {})
        df = pd.DataFrame([{
            "Apply": overrides.get(e["id"], e.get("enabled", False)), "Date": e["date"],
            "Event": EVENT_LABELS.get(e["type"], e["type"]), "Hours": event_hours(e, params),
            "Faces hit": event_faces(e, pcfg), "Section": e.get("stretch") or e.get("corridor") or ", ".join(e.get("areas", [])),
            "Confidence": e.get("confidence", 0), "Articles": len(e.get("articles", [])), "Source": e.get("source", ""),
            "id": e["id"]} for e in events])
        edited = st.data_editor(df, hide_index=True, width="stretch", key="events_editor",
                                disabled=[c for c in df.columns if c != "Apply"], column_order=[c for c in df.columns if c != "id"],
                                column_config={"Apply": st.column_config.CheckboxColumn("Apply", help="Use this event in the forecast"),
                                               "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.2f")})
        new = {r["id"]: bool(r["Apply"]) for r in edited.to_dict("records")}
        if new != {r["id"]: bool(r["Apply"]) for r in df.to_dict("records")}:
            st.session_state["event_overrides"] = {**overrides, **new}
            st.rerun()

        st.subheader("Effect on the forecast")
        rows = []
        for pid, f in res.forecasts.items():
            day_hits = {h["date"]: h["change"] for h in f.applied}
            rows.append({"Face": name_of(res, pid), "Events applied": len({h["event"] for h in f.applied}),
                         "Worst day": min(day_hits, key=day_hits.get) if day_hits else "—",
                         "Worst-day change": min(day_hits.values()) if day_hits else 0.0,
                         "Campaign change": f.adjusted.value / f.baseline.value - 1 if f.baseline.value else 0.0,
                         "Adjusted impressions": f.adjusted.value})
        st.dataframe(pd.DataFrame(rows).style.format({"Worst-day change": "{:+.1%}", "Campaign change": "{:+.2%}",
                                                       "Adjusted impressions": "{:,.0f}"}),
                     hide_index=True, width="stretch")
        for e in events:
            if e.get("citations"):
                with st.expander(f"Sources for {EVENT_LABELS.get(e['type'], e['type'])} on {e['date']}"):
                    for c in e["citations"]:
                        st.markdown(f"- [{c.get('title') or c['url']}]({c['url']})")

    st.subheader("Signal ledger")
    status = st.segmented_control("Show", ["Kept", "Pending", "Filtered out"], default="Kept", key="ledger_filter")
    want = {"Kept": "applied", "Pending": "pending", "Filtered out": "rejected"}.get(status or "Kept")
    arts = sorted((a for a in ledger.articles.values() if a["status"] == want),
                  key=lambda a: a.get("published", ""), reverse=True)
    for a in arts[:60]:
        color = STATUS_COLORS[a["status"]]
        st.markdown(f"<span style='border:1px solid {color};color:{color};border-radius:10px;padding:0 7px;"
                    f"font-size:0.72rem'>{a['status']}</span> [{a['title']}]({a.get('url', '')}) "
                    f"<span style='opacity:0.6;font-size:0.8rem'>{a.get('source', '')} · {a.get('published', '')} · "
                    f"{', '.join(a.get('placements', []))}</span><br/>"
                    f"<span style='opacity:0.65;font-size:0.8rem'>{a.get('reason', '')}</span>", unsafe_allow_html=True)
    if not arts:
        st.caption("Nothing in this group.")
    st.caption("Sources: Google News RSS (region AE), GDELT DOC 2.0 and Claude web search (cited). Headlines and "
               "links only are stored in data/signals/ledger.json; extractions are frozen once made. A commercial "
               "product needs a licensed news API.")


def page_sources(res: Results, pcfg, params: Params, focus: str | None = None) -> None:
    page_header("", "Data sources", "")
    want = st.session_state.get("src_num")
    if focus and want and want[0] == focus:       # arrived from an ⓘ on Locations: answer that first
        asked = next((x for x in location_numbers(res, pcfg, params, focus) if x["key"] == want[1]), None)
        if asked:
            st.markdown(source_card(asked, "You asked about · ")
                        + f"<a class='jump' href='#loc-numbers'>See every number for {html.escape(name_of(res, focus))} "
                          "and its source ↓</a>", unsafe_allow_html=True)
    st.markdown("<div class='ooh-sec'>① How the data flows</div>", unsafe_allow_html=True)
    data = diagram_data()
    srcs = data["sources"]
    connected = [x for x in srcs if x["status"] != "not connected"]
    sample = [x for x in srcs if x["status"] == "sample"]
    live = [x for x in srcs if x["status"] in ("live", "cached")]
    ai = data["engine"]["ai"]
    st.markdown(
        f"<span class='ooh-live'></span>**{len(live)}** live or cached · **{len(connected)}** of {len(srcs)} "
        f"connected · **{len(sample)}** still placeholders · Claude: **{ai['status']}**. "
        "Every source files facts into the knowledge layer; the campaign picks the facts it needs. "
        "Links below are counted from those facts, so a source only shows a link it actually feeds.",
        unsafe_allow_html=True)
    flow = flow_payload(res, pcfg, params)
    html_block(flow_viz.flow_html(flow), height=760)
    derived = {x["id"]: x for x in flow["sources"]}
    for x in srcs:
        d = derived.get(x["id"], {})
        x["feeds_names"] = ([sources_mod.OUTPUTS.get(o, o) for o in d.get("feeds", [])]
                            or (["context only"] if d.get("facts") else ["—"]))
        x["facts_n"] = d.get("facts", 0)

    st.markdown("<div class='ooh-sec'>② How far to trust each source</div>", unsafe_allow_html=True)
    df = pd.DataFrame([{
        "Source": x["name"], "Status": x["status"], "Confidence": x["score"], "Potential": x["potential"],
        "Label of its numbers": x["label"], "Facts": x["facts_n"], "Feeds": ", ".join(x["feeds_names"]),
        "Note": x["status_note"], "Upgrade": x["upgrade"], "Link": x["url"],
    } for x in sorted(srcs, key=lambda x: -x["score"])])
    st.dataframe(df, hide_index=True, width="stretch", height=460, column_config={
        "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%d"),
        "Potential": st.column_config.ProgressColumn("Potential once connected", min_value=0, max_value=100,
                                                     format="%d"),
        "Link": st.column_config.LinkColumn("Link"),
    })
    with st.expander("How the confidence score works"):
        st.latex(r"\text{score} = 100 \times s \times (0.40\,p + 0.35\,d + 0.25\,f)")
        st.markdown(
            "- **p, provenance:** who stands behind the data (official publication 1.0, commercial 0.85, "
            "OpenStreetMap 0.75, model assumption 0.4).\n"
            "- **d, directness:** how directly it measures what the model uses it for.\n"
            "- **f, freshness:** live today 1.0, cached within 30 days 0.85, static publication 0.6.\n"
            "- **s, status factor:** live, cached or configured 1.0; placeholder (SAMPLE) 0.35; not connected 0.\n"
            "- **Potential** is the score once connected and live (s = 1, f = 1).\n\n"
            f"The score is a planning heuristic {badge('ASSUMPTION')}. It is separate from the VERIFIED / "
            "ESTIMATE / SAMPLE labels on individual numbers, and it never enters the reach calculation.",
            unsafe_allow_html=True)
    st.caption("Status is read locally: API keys present, cache dates and is_sample flags. Opening this page "
               "calls no external service.")
    if focus:
        location_sources(res, pcfg, params, focus)


def page_map(res: Results, params: Params, pid: str, pcfg=None) -> None:
    aud = pcfg.campaign.audience if pcfg else "in the target audience"
    st.header("Where the billboards are, and which roads can see them")
    view_mode = st.radio("View", ["All placements", "Location in focus"], horizontal=True,
                         key="map_view", label_visibility="collapsed")
    st.caption("Segments are coloured by visibility score V (light blue = low, deep navy = high). Hover for the "
               "factor breakdown and volume source.")
    radius, half = params.base("cone_radius_m"), params.base("half_angle_deg")
    seg_rows, cone_rows, pin_rows, metro_rows = [], [], [], []
    vmax = max((float(r.scored["V"].max()) for r in res.placements.values() if not r.scored.empty), default=1)
    for r in res.placements.values():
        s, p = r.prep.snapped, r.prep.placement
        flows = r.reach.scenarios["base"].flows.set_index("flow") if len(r.reach.scenarios["base"].flows) else None
        if not r.scored.empty:
            for row in r.scored[r.scored["included"]].itertuples():
                vol = flows.loc[row.flow, "vehicles_day"] if flows is not None and row.flow in flows.index else 0
                seg_rows.append({
                    "path": lonlat_path(row.geometry), "color": v_color(row.V, vmax),
                    "tooltip": (f"<b>{p.label} · {row.label}</b> ({row.highway})<br/>V = {row.V:.3f} = "
                                f"D {row.D:.2f} × A {row.A:.2f} × O {row.O:.2f} × S {row.S:.2f} × T {row.T:.2f}"
                                f"<br/>{row.dist_m:.0f} m from face · {row.lanes} lanes ({row.lanes_source})"
                                f"<br/>Flow volume {vol:,.0f} vehicles/day · capacity fallback (ESTIMATE)"
                                f"{'<br/>Line of sight crosses a building' if row.blocked else ''}"),
                })
        if not r.metro_scored.empty:
            for row in r.metro_scored[r.metro_scored["included"]].itertuples():
                metro_rows.append({"path": lonlat_path(row.geometry),
                                   "tooltip": f"<b>{p.label} · metro track</b><br/>V = {row.V:.3f}"})
        cone_rows.append({"polygon": cone_polygon_lonlat(s.lon, s.lat, s.facing_bearing_deg, radius, half),
                          "tooltip": f"<b>{p.label}: where the board can be seen</b><br/>up to {radius:.0f} m away"})
        u = r.metrics["unique_month"]
        rr = r.profile.relevant_reach
        pin_rows.append({"position": [s.lon, s.lat], "label": p.label,
                         "tooltip": (f"<b>{p.label}</b> · {road_short(p.corridor)}<br/>{p.type.title()} board, "
                                     f"{p.width_m:g} × {p.height_m:g} m<br/>{exec_ui.people(u.value)} people pass a "
                                     f"month (likely {exec_ui.people(u.low)}–{exec_ui.people(u.high)})<br/>"
                                     f"{exec_ui.people(rr.value)} of them are {aud}")})
    layers = [
        pdk.Layer("PolygonLayer", cone_rows, get_polygon="polygon", get_fill_color=[98, 80, 214, 26],
                  get_line_color=[98, 80, 214, 150], line_width_min_pixels=1, pickable=True),
        pdk.Layer("PathLayer", seg_rows, get_path="path", get_color="color", width_min_pixels=4,
                  pickable=True),
        pdk.Layer("PathLayer", metro_rows, get_path="path", get_color=[229, 72, 77, 220], width_min_pixels=3,
                  pickable=True),
        pdk.Layer("ScatterplotLayer", pin_rows, get_position="position", get_radius=40,
                  get_fill_color=[229, 72, 77, 255], get_line_color=[255, 255, 255], line_width_min_pixels=2,
                  stroked=True, radius_min_pixels=6, pickable=True),
        pdk.Layer("TextLayer", pin_rows, get_position="position", get_text="label", get_size=15,
                  get_color=[29, 27, 46], get_pixel_offset=[0, -18]),
    ]
    if view_mode == "All placements":
        lats = [r.prep.snapped.lat for r in res.placements.values()]
        lons = [r.prep.snapped.lon for r in res.placements.values()]
        view = pdk.ViewState(latitude=float(np.mean(lats)), longitude=float(np.mean(lons)), zoom=11.0, pitch=0)
    else:
        focus = res.placements[pid].prep.snapped
        view = pdk.ViewState(latitude=focus.lat, longitude=focus.lon, zoom=14.6, pitch=0)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="light",
                             tooltip={"html": "{tooltip}", "style": {"fontSize": "12px"}}), height=560)
    st.caption("Basemap © CARTO, data © OpenStreetMap contributors. Switch to 'Location in focus' to zoom "
               "into the location picked at the top.")
    plan_ids = {x.placement for x in res.plan}
    rows = []
    for r in res.placements.values():
        p = r.prep.placement
        rows.append({"Location": p.label, "Road": p.corridor, "Board": p.type.title(),
                     "Size": f"{p.width_m:g} × {p.height_m:g} m",
                     "People passing / month": exec_ui.people(r.metrics["unique_month"].value),
                     f"{cap(pcfg.campaign.audience_short) if pcfg else 'Target'} / month":
                         exec_ui.people(r.profile.relevant_reach.value),
                     "In our pick": "⭐ Yes" if p.id in plan_ids else "No"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Where each board sits on the road and which way it faces are in Assumptions and sources "
               "(snapping log).")


def page_detail(res: Results, pid: str, params: Params, use_llm: bool, brand: str) -> None:
    r = res.placements[pid]
    p, s, m, prof = r.prep.placement, r.prep.snapped, r.metrics, r.profile
    st.header(f"{p.label} · {p.corridor}")
    st.markdown(f"{p.type.title()} face, {p.width_m:g} × {p.height_m:g} m, facing {s.facing_bearing_deg:.0f}° "
                f"towards traffic on {s.road_name}. Share of voice {p.share_of_voice:.2f}. "
                f"Example brief: {brand}.")

    kpi_strip([
        ("Impressions / day", m["impressions_day"].value, "", m["impressions_day"].label),
        ("Unique people / month", m["unique_month"].value, "", m["unique_month"].label),
        ("Target audience / month", prof.relevant_reach.value, "", prof.relevant_reach.label),
        ("Mean visibility", r.reach.mean_visibility * 100, "/ 100", "ESTIMATE"),
    ])
    st.subheader("The planner's five questions")
    u, rr = m["unique_month"], prof.relevant_reach
    rank = sorted(res.placements.values(), key=lambda x: -x.profile.relevant_reach.value)
    pos = [x.id for x in rank].index(pid) + 1
    q = pd.DataFrame([
        ["Estimated unique monthly audience?",
         f"{fmt_num(u.value)} people (range {fmt_num(u.low)} to {fmt_num(u.high)})", u.label],
        ["What audience characteristics?",
         "; ".join(prof.segments["Demographic"][:2]) + "; " + prof.segments["Behavioural"][1], "ESTIMATE"
         if not prof.meta_is_sample else "SAMPLE"],
        ["How does it compare with alternatives?",
         f"Ranks {pos} of {len(rank)} on target-audience reach ({fmt_num(rr.value)} people/month); see Compare",
         rr.label],
        ["Delivery against the original plan?",
         (f"News-adjusted forecast {res.forecasts[pid].adjusted.value / res.forecasts[pid].baseline.value - 1:+.1%} "
          f"vs plan ({len({h['event'] for h in res.forecasts[pid].applied})} event(s)); delivery index "
          f"{res.delivery[res.delivery['placement'] == pid]['delivery_index'].mean():.2f} (simulated actual); "
          "see Planned vs actual and Area signals"), "ESTIMATE"],
        ["Can the exposed audience be re-engaged?",
         "Zone exported as GeoJSON and radius list; live re-targeting needs a data partner", "CONCEPT"],
    ], columns=["Question", "MVP answer", "Label"])
    rows = "".join(f"| {a} | {b} | {badge(c)} |\n" for a, b, c in q.itertuples(index=False))
    st.markdown("| Question | MVP answer | Label |\n| --- | --- | --- |\n" + rows, unsafe_allow_html=True)

    st.subheader("Reach funnel")
    cols = st.columns(3)
    with cols[0]:
        metric_card("Vehicles passing (facing direction)", m["vehicles_day"], "/day")
        metric_card("People in those vehicles", m["people_day"], "/day")
    with cols[1]:
        metric_card("Visible impressions (placement, SOV = 1)", m["impressions_day"], "/day")
        metric_card("Monthly impressions", m["impressions_month"], "/month")
    with cols[2]:
        metric_card("Unique people", m["unique_month"], "/month")
        metric_card("Target-audience people", prof.relevant_reach, "/month")
    if p.type == "digital":
        metric_card(f"Advertiser impressions (one slot, SOV {p.share_of_voice:.2f})",
                    m["advertiser_impressions_day"], "/day")

    stages = [("Vehicles / day", m["vehicles_day"]), ("People / day", m["people_day"]),
              ("Visible impressions / day", m["impressions_day"]),
              ("Impressions / month", m["impressions_month"]), ("Unique people / month", m["unique_month"]),
              ("Target audience / month", prof.relevant_reach)]
    fig = go.Figure(go.Bar(
        y=[n for n, _ in stages][::-1], x=[v.value for _, v in stages][::-1], orientation="h",
        marker_color=SERIES[0],
        error_x=dict(type="data", symmetric=False, array=[v.high - v.value for _, v in stages][::-1],
                     arrayminus=[v.value - v.low for _, v in stages][::-1], color="#bbbbbb", thickness=1.5),
        text=[f"{fmt_num(v.value)} ({fmt_num(v.low)}–{fmt_num(v.high)})" for _, v in stages][::-1],
        textposition="inside", insidetextanchor="start", textfont=dict(color="white")))
    ticks = [1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7]
    fig.update_layout(**PLOT_LAYOUT, height=330, title_text="Funnel, base value with low–high range (log scale)",
                      xaxis=dict(type="log", tickvals=ticks, ticktext=[fmt_num(t) for t in ticks]))
    st.plotly_chart(fig, width="stretch")

    st.subheader("Hourly impressions (placement, base day)")
    hours = list(range(24))
    sc = r.reach.scenarios
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=sc["high"].hourly_impressions, line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=hours, y=sc["low"].hourly_impressions, fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(76,154,255,0.22)", name="low–high range"))
    fig.add_trace(go.Scatter(x=hours, y=sc["base"].hourly_impressions, line=dict(color=SERIES[0], width=2.5),
                             name="base"))
    fig.update_layout(**PLOT_LAYOUT, height=300, xaxis_title="Hour of day",
                      yaxis_title="Impressions per hour", legend=LEGEND_TOP)
    st.plotly_chart(fig, width="stretch")
    capped = sc["high"].capped_hours
    label_line(f"Hourly shape: default commuter curve. "
               f"{'Hourly lane capacity capped ' + str(capped) + ' flow-hours in the high case.' if capped else 'No hour exceeds lane capacity.'}",
               "ASSUMPTION")

    st.subheader("Audience persona")
    if use_llm:
        text, source = narrative_mod.narrative(r.facts, brand, use_llm=True)
    else:
        text, source = narrative_mod.narrative(r.facts, brand, use_llm=False)
    st.markdown(f"<div style='border-left:3px solid {SERIES[0]};padding:6px 12px'>"
                f"{text.replace(chr(10), '<br/>')}</div>", unsafe_allow_html=True)
    st.caption(f"Narrative: {source}.")
    seg_cols = st.columns(3)
    for col, (name, items) in zip(seg_cols, prof.segments.items()):
        with col:
            st.markdown(f"**{name}**")
            for it in items:
                st.markdown(f"- {it}")
    label_line("Demographics and interest share come from Meta reach estimates.",
               "SAMPLE" if prof.meta_is_sample else "ESTIMATE")
    poi = pd.DataFrame([{"category": k, "count within 1 km": v} for k, v in prof.poi_counts.items()])
    c1, c2 = st.columns(2)
    with c1:
        st.dataframe(poi, hide_index=True, width="stretch")
        st.caption("OpenStreetMap points of interest (VERIFIED as mapped; coverage is incomplete).")
    with c2:
        t = prof.triangulation
        if t:
            msg = (f"Computed unique audience {fmt_num(t['computed_unique'])} vs Meta reach estimate "
                   f"{fmt_num(t['meta_audience'])}: ratio {t['ratio']:.2f}. ")
            msg += ("Outside the ±{:.0f}x band: check volume and frequency.".format(t["limit"]) if t["flag"]
                    else "Within the ±{:.0f}x band.".format(t["limit"]))
            (st.warning if t["flag"] else st.success)(msg)
            label_line("Triangulation input", t["label"])
        if r.reach.metro:
            mi = r.reach.metro
            label_line(f"Metro: nearest station {mi.station}, {fmt_num(mi.daily_riders)} riders/day; "
                       f"adds {fmt_num(m['metro_impressions_day'].value)} impressions/day.", mi.label)
        else:
            st.caption("No metro track inside the exposure cone.")

    st.subheader("News-adjusted campaign forecast")
    f = res.forecasts[pid]
    change = f.adjusted.value / f.baseline.value - 1 if f.baseline.value else 0.0
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card(f"Campaign impressions, baseline ({len(f.days)} days)", f.baseline, "")
    with c2:
        metric_card(f"Campaign impressions, news-adjusted ({change:+.1%})", f.adjusted, "")
    with c3:
        metric_card("Unique people, news-adjusted", f.unique_adjusted, "/month")
    if f.applied:
        days = pd.DataFrame(f.applied)
        st.markdown("".join(
            f"- **{h['date']}** · {EVENT_LABELS.get(h['type'], h['type'])}: {h['change']:+.1%} that day "
            f"({fmt_num(h['impressions_delta'])} impressions)\n" for h in days.drop_duplicates("date").to_dict("records")))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=f.days, y=f.baseline_daily, name="Baseline", line=dict(color="#6b7280", width=2)))
        fig.add_trace(go.Scatter(x=f.days, y=f.adjusted_daily, name="News-adjusted", fill="tonexty",
                                 fillcolor="rgba(229,72,77,0.18)", line=dict(color=SERIES[0], width=2.5)))
        fig.update_layout(**PLOT_LAYOUT, height=260, title_text="Daily impressions over the campaign",
                          yaxis_title="Impressions / day", legend=LEGEND_TOP)
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No switched-on event touches this face in the campaign window.")
    st.caption("Events come from the Area signals page: Claude dates them from headlines and web search; the "
               "effect sizes are ASSUMPTIONS in config (Events group in the sidebar).")

    with st.expander("Traffic flows inside the cone (base case)"):
        flows = sc["base"].flows
        if len(flows):
            show = flows[["road", "highway", "lanes", "lanes_source", "segments", "visible_length_m",
                          "speed_kmh", "mean_V", "vehicles_day", "impressions_day"]].copy()
            st.dataframe(show.style.format({"visible_length_m": "{:.0f}", "speed_kmh": "{:.0f}", "mean_V": "{:.3f}",
                                            "vehicles_day": "{:,.0f}", "impressions_day": "{:,.0f}"}),
                         hide_index=True, width="stretch")
        st.caption("Volume source: RTA capacity fallback (lanes × 2,000 × utilisation × class factor × 24), "
                   "capped per hour at lane capacity. Dwell T uses the visible approach length / speed per flow.")


def page_duplication(res: Results, boards: int) -> None:
    st.header("Duplication and plan")
    mat = res.overlap
    ids = list(mat.index)
    share = mat.copy()
    for a in ids:
        for b in ids:
            share.loc[a, b] = mat.loc[a, b] / min(mat.loc[a, a], mat.loc[b, b]) if a != b else 1.0
    text = [[(f"{fmt_num(mat.loc[a, b])}<br>{share.loc[a, b]:.0%}" if a != b else f"{fmt_num(mat.loc[a, a])}<br>own")
             for b in ids] for a in ids]
    off = share.where(~np.eye(len(ids), dtype=bool))
    names = [name_of(res, i) for i in ids]
    fig = go.Figure(go.Heatmap(z=off.values, x=names, y=names, text=text, texttemplate="%{text}",
                               colorscale="Blues", zmin=0, zmax=max(0.6, float(np.nanmax(off.values)) if len(ids) > 1 else 1),
                               colorbar=dict(title="share of smaller", tickformat=".0%"),
                               hovertemplate="%{y} × %{x}<br>%{text}<extra></extra>"))
    fig.update_layout(**PLOT_LAYOUT, height=420, title_text="Overlap in unique people per month (and % of the smaller audience)")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")
    label_line("Overlap uses shared road segments, or the corridor rule (tau) when larger.", "ASSUMPTION")
    rules = [{"pair": f"{name_of(res, a)} × {name_of(res, b)}", "rule": res.overlap_rules.loc[a, b],
              "overlap people": mat.loc[a, b]}
             for i, a in enumerate(ids) for b in ids[i + 1:]]
    st.dataframe(pd.DataFrame(rules).style.format({"overlap people": "{:,.0f}"}), hide_index=True,
                 width="stretch")

    st.subheader(f"Best mix of {boards} boards")
    if not res.plan:
        st.info("No plan: the brief books no boards.")
        return
    plan = pd.DataFrame([s.__dict__ for s in res.plan])
    plan["placement"] = plan["placement"].map(lambda i: name_of(res, i))
    st.dataframe(plan.rename(columns={
        "step": "Step", "placement": "Add", "incremental_relevant": "New relevant reach it adds",
        "combined_relevant": "Combined relevant reach", "naive_relevant": "Naive sum"}).style.format(
        {"New relevant reach it adds": "{:,.0f}", "Combined relevant reach": "{:,.0f}", "Naive sum": "{:,.0f}"}),
        hide_index=True, width="stretch")
    st.caption("Every mix of this many boards is tried; the one reaching the most relevant people (shared people "
               "counted once) wins. Boards are listed in the order that adds the most first. No prices are used.")
    last = res.plan[-1]
    lost = last.naive_relevant - last.combined_relevant
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[f"Step {s.step}: +{name_of(res, s.placement)}" for s in res.plan], y=[s.naive_relevant for s in res.plan],
                         name="Naive sum", marker_color="#6b7280"))
    fig.add_trace(go.Bar(x=[f"Step {s.step}: +{name_of(res, s.placement)}" for s in res.plan],
                         y=[s.combined_relevant for s in res.plan], name="Combined (de-duplicated)",
                         marker_color=SERIES[0]))
    fig.update_layout(**PLOT_LAYOUT, barmode="group", height=340, yaxis_title="Target-audience people / month",
                      title_text=f"Duplication removes {fmt_num(lost)} people ({lost / last.naive_relevant:.0%}) from the naive sum",
                      legend=LEGEND_TOP)
    st.plotly_chart(fig, width="stretch")
    label_line(f"All four placements: {fmt_num(res.combined_unique_all)} combined unique people vs "
               f"{fmt_num(res.naive_unique)} naive sum.", "ESTIMATE")


# --------------------------------------------------------------------------- the four main pages (the brief's story)

LABEL_KIND = {"Confirmed": "good", "Estimate": "accent", "Estimate on sample inputs": "accent", "Assumption": "warn",
              "Concept": "crit", "Simulated": "warn"}


def lbl(label: str) -> str:
    """A label chip in the brief's words (Confirmed / Estimate / Assumption / Concept)."""
    text = exec_ui.ENGINE_TO_BRIEF.get(label, label)
    return f"<span class='lbl {LABEL_KIND.get(text, '')}'>{html.escape(text)}</span>"


def location_map(res: Results, pcfg, params: Params, focus: str, close: bool, key: str, height: int,
                 clickable: bool = True):
    """Every board with its viewing cone, the roads that see it and its pin; close-up or city view."""
    c = pcfg.campaign
    faces = {f["id"]: f for f in face_rows(res, focus)}
    plan_ids = [s.placement for s in res.plan]
    radius, half = params.base("cone_radius_m"), params.base("half_angle_deg")
    seg_rows, cone_rows, pin_rows = [], [], []
    vmax = max((float(r.scored["V"].max()) for r in res.placements.values() if not r.scored.empty), default=1)
    for pid, r in res.placements.items():
        s, p, f = r.prep.snapped, r.prep.placement, faces[pid]
        rgb = [int(f["color"][i:i + 2], 16) for i in (1, 3, 5)]
        flows = r.reach.scenarios["base"].flows.set_index("flow") if len(r.reach.scenarios["base"].flows) else None
        if not r.scored.empty:
            for row in r.scored[r.scored["included"]].itertuples():
                vol = flows.loc[row.flow, "vehicles_day"] if flows is not None and row.flow in flows.index else 0
                seg_rows.append({"path": lonlat_path(row.geometry), "color": v_color(row.V, vmax),
                                 "tooltip": (f"<b>{html.escape(p.label)}</b> · road in view: {html.escape(str(row.label))}"
                                             f"<br/>{exec_ui.people(vol)} vehicles a day · visibility {row.V:.2f}")})
        cone_rows.append({"polygon": cone_polygon_lonlat(s.lon, s.lat, s.facing_bearing_deg, radius, half),
                          "fill": rgb + [70 if pid == focus else 40], "line": rgb + [200],
                          "tooltip": f"<b>{html.escape(p.label)}</b>: where the board can be seen (up to {radius:.0f} m)"})
        pin_rows.append({"position": [s.lon, s.lat], "label": p.label, "pid": pid, "color": rgb + [255],
                         "r": (18 if close else 90 if pid == focus else 55),
                         "tooltip": (f"<b>{html.escape(p.label)}</b> · {road_short(p.corridor)}<br/>"
                                     f"{exec_ui.people(r.metrics['impressions_day'].value)} impressions a day · "
                                     f"{exec_ui.people(r.metrics['unique_month'].value)} people a month<br/>"
                                     f"{exec_ui.people(r.profile.relevant_reach.value)} {html.escape(c.audience_short)}"
                                     f"{'<br/>⭐ in our plan' if pid in plan_ids else ''}"
                                     f"{'<br/><i>Click to select</i>' if clickable else ''}")})
    layers = [
        pdk.Layer("PolygonLayer", cone_rows, id="cones", get_polygon="polygon", get_fill_color="fill",
                  get_line_color="line", line_width_min_pixels=1, pickable=True),
        pdk.Layer("PathLayer", seg_rows, id="roads", get_path="path", get_color="color",
                  width_min_pixels=4 if close else 3, pickable=True),
        pdk.Layer("ScatterplotLayer", [x for x in pin_rows if x["pid"] == focus], id="focus_ring",
                  get_position="position", get_radius=45 if close else 260, get_fill_color=[98, 80, 214, 30],
                  get_line_color=[98, 80, 214, 200], line_width_min_pixels=2, stroked=True,
                  radius_min_pixels=14 if close else 18),
        pdk.Layer("ScatterplotLayer", pin_rows, id="pins", get_position="position", get_radius="r",
                  get_fill_color="color", get_line_color=[255, 255, 255], line_width_min_pixels=3, stroked=True,
                  radius_min_pixels=8, pickable=True),
        pdk.Layer("TextLayer", pin_rows, id="labels", get_position="position", get_text="label", get_size=14,
                  get_color=[29, 27, 46], get_pixel_offset=[0, -24], font_weight=700,
                  outline_width=4, outline_color=[255, 255, 255, 255], font_settings={"sdf": True}),
    ]
    fs = res.placements[focus].prep.snapped
    lats = [r.prep.snapped.lat for r in res.placements.values()]
    lons = [r.prep.snapped.lon for r in res.placements.values()]
    view = (pdk.ViewState(latitude=fs.lat, longitude=fs.lon, zoom=15.1, pitch=0) if close else
            pdk.ViewState(latitude=float(np.mean(lats)), longitude=float(np.mean(lons)), zoom=10.75, pitch=0))
    deck = pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="light",
                    tooltip={"html": "{tooltip}", "style": {"fontSize": "12.5px"}})
    if not clickable:
        st.pydeck_chart(deck, height=height, key=key)
        return
    event = st.pydeck_chart(deck, height=height, on_select="rerun", selection_mode="single-object", key=key)
    picked = (getattr(event, "selection", None) or {}).get("objects", {}) if event else {}
    objs = picked.get("pins") or []
    sel = objs[0].get("pid") if objs else None
    last = f"_{key}_last"
    if sel != st.session_state.get(last):      # act on a new click only
        st.session_state[last] = sel
        if sel and sel != focus:
            goto(focus=sel)


# --------------------------------------------------------------------------- numbers and their sources

NUM_GROUPS = ["Traffic", "Visibility", "Reach", "Audience", "Nearby (1 km)", "Board", "Delivery", "In the news"]
_TOPIC_GROUP = {"traffic": "Traffic", "visibility": "Visibility", "audience": "Audience", "places": "Nearby (1 km)",
                "media": "Board", "delivery": "Delivery", "crowds": "In the news", "growth": "In the news",
                "road_events": "In the news"}
_REACH_KEYS = {"unique", "road_share"}


@st.cache_data(show_spinner=False)
def _registry() -> dict:
    return {s.id: {"name": s.name, "status": s.status, "score": s.score, "url": s.url, "provider": s.provider,
                   "what": s.what} for s in sources_mod.registry()}


def num_row(group, key, title, display, label, sources, detail="", url="", quote="", value=None,
            reg: dict | None = None) -> dict:
    """One number with its sources, in the shape every drill-down uses."""
    reg = reg or _registry()
    srcs = [reg[s] | {"id": s} for s in sources if s in reg]
    return {"group": group, "key": key, "title": title, "display": display, "label": label,
            "sources": srcs, "source": " + ".join(s["name"] for s in srcs) or "—",
            "score": min((s["score"] for s in srcs), default=0), "detail": detail,
            "url": url or next((s["url"] for s in srcs if s["url"]), ""), "quote": quote, "value": value}


def location_numbers(res: Results, pcfg, params: Params, pid: str) -> list[dict]:
    """Every number we hold for one location, with the source behind it.

    Built from the knowledge layer (one fact per number, each naming its sources) plus the reach numbers the
    engine computes from them. Order: NUM_GROUPS, then as filed.
    """
    c = pcfg.campaign
    r, reg = res.placements[pid], _registry()
    m, p = r.metrics, r.prep.placement
    rows: list[dict] = []

    def add(group, key, title, display, label, sources, detail="", url="", quote="", value=None):
        rows.append(num_row(group, key, title, display, label, sources, detail, url, quote, value, reg))

    for f in knowledge_facts(res, pcfg, params):
        if f.location != pid:
            continue
        key = f.id.split(":", 1)[1]
        group = "Reach" if key in _REACH_KEYS else _TOPIC_GROUP.get(f.topic, "Board")
        if f.id.startswith(f"{pid}:people:") and f.topic in ("traffic", "places"):
            group = "In the news"
        add(group, key, f.title, f.display, f.trust, f.sources, f.detail, f.url, f.quote, f.value)
    um = m["unique_month"]
    add("Reach", "impressions_day", "Impressions a day", exec_ui.people(m["impressions_day"].value),
        m["impressions_day"].label, ["rta", "osm", "assumptions", "metro"],
        "People passing a day × the chance of noticing the board (distance, angle, size, speed), plus metro riders")
    add("Reach", "unique_range", "Unique people a month: low to high",
        f"{exec_ui.people(um.low)} – {exec_ui.people(um.high)}", um.label, ["assumptions"],
        "The range comes mostly from how often the same people pass in a month (an assumption until mobile data)")
    add("Reach", "relevant", f"{cap(c.audience_short)} a month", exec_ui.people(r.profile.relevant_reach.value),
        r.profile.relevant_reach.label, ["meta", "briefs"],
        f"Unique people a month × the share who are {c.audience} (Meta interest share for this area)")
    if p.type == "digital" and p.share_of_voice < 1:
        add("Reach", "adv", "Views of our ad a day", exec_ui.people(m["advertiser_impressions_day"].value),
            m["advertiser_impressions_day"].label, ["inventory", "rta"],
            f"Impressions × our share of the screen (our ad is 1 in {round(1 / p.share_of_voice)})")
    order = {g: i for i, g in enumerate(NUM_GROUPS)}
    return sorted(rows, key=lambda x: order.get(x["group"], 99))


def _num_index(res: Results, pcfg, params: Params, pid: str) -> dict:
    return {x["key"]: x for x in location_numbers(res, pcfg, params, pid)}


def source_card(row: dict, where: str = "") -> str:
    """The drill-down for one number: what it is, where it comes from, how much to trust it."""
    srcs = "".join(
        f"<div class='sc-src'><b>{html.escape(s['name'])}</b> · {html.escape(s['provider'])} · "
        f"{html.escape(s['status'])} · confidence <b>{s['score']}</b>/100"
        + (f" · <a href='{html.escape(s['url'])}' target='_blank'>open source ↗</a>" if s["url"] else "")
        + f"<br/><span>{html.escape(s['what'])}</span></div>" for s in row["sources"])
    quote = (f"<div class='sc-q'>“{html.escape(row['quote'][:260])}{'…' if len(row['quote']) > 260 else ''}”"
             + (f" <a href='{html.escape(row['url'])}' target='_blank'>read the article ↗</a>" if row["url"] else "")
             + "</div>") if row["quote"] else ""
    return (f"<div class='sc'><div class='sc-h'>{html.escape(where)}{html.escape(row['title'])}: "
            f"<b>{html.escape(row['display'])}</b> {lbl(row['label'])}</div>"
            + (f"<div class='sc-d'>How we get it: {html.escape(row['detail'])}</div>" if row["detail"] else "")
            + quote + srcs + "</div>")


def how_we_know(rows: list[dict], title: str = "How we know") -> None:
    """An expander that drills from the numbers on screen down to their sources."""
    rows = [x for x in rows if x]
    if not rows:
        return
    with st.expander(f"🔎 {title}"):
        st.markdown("".join(source_card(x) for x in rows), unsafe_allow_html=True)
        st.caption("Full list for this location: Data sources page.")


def road_share(r) -> float:
    """Share of a board's views that come from drivers (the rest from metro riders)."""
    base = r.reach.scenarios["base"]
    return base.road_impressions_day / base.impressions_day if base.impressions_day else 1.0


def num_tile(title: str, value: str, label: str, sub: str = "") -> str:
    return (f"<div class='nt'><div class='nt-t'>{html.escape(title)}</div><div class='nt-v'>{value}</div>"
            f"<div class='nt-s'>{sub}{' · ' if sub else ''}{lbl(label)}</div></div>")


def dots(level: int, of: int = 4) -> str:
    return f"<span class='dots'>{knowledge_mod.rating(level, of)}</span>"


def location_picker(res: Results, focus: str, key: str, label: str = "Location") -> str:
    ids = list(res.placements)
    pick = st.segmented_control(label, ids, default=focus, key=f"{key}_{focus}", format_func=lambda i: name_of(res, i))
    if pick and pick != focus:
        goto(focus=pick)
    return focus


# --------------------------------------------------------------------------- screen 1: locations


def info_tile(title: str, value: str, sub: str, num_key: str, focus: str) -> None:
    """A number tile whose title is a button: ⓘ opens the Data sources page on the source of that number."""
    with st.container(border=True):
        if st.button(f"{title}  ⓘ", key=f"info_{num_key}_{focus}", type="tertiary",
                     help="Where this number comes from"):
            st.session_state["src_num"] = (focus, num_key)
            goto("Data sources", focus)
        st.markdown(f"<div class='nt-v'>{value}</div><div class='nt-s'>{sub or '&nbsp;'}</div>",
                    unsafe_allow_html=True)


def page_locations(res: Results, pcfg, params: Params, focus: str) -> None:
    c = pcfg.campaign
    r = res.placements[focus]
    p, m = r.prep.placement, r.metrics
    st.session_state.pop("src_num", None)          # an ⓘ click is answered once, on the Data sources page
    page_header("", "Billboard locations", "")
    location_picker(res, focus, "loc_pick")
    col_map, col_num = st.columns([1.5, 1], gap="medium")
    with col_map:
        location_map(res, pcfg, params, focus, close=True, key=f"loc_close_{focus}", height=470, clickable=False)
        st.caption(f"{p.label} · {p.corridor} · {p.type} board {p.width_m:g} × {p.height_m:g} m. Wedge = where it can "
                   "be seen; darker roads = better view.")
    with col_num:
        um = m["unique_month"]
        tiles = [
            ("Vehicles a day", exec_ui.people(m["vehicles_day"].value), "", "vehicles"),
            ("People a day", exec_ui.people(m["people_day"].value), "", "people_day"),
            ("Impressions a day", exec_ui.people(m["impressions_day"].value), "", "impressions_day"),
            ("Unique people a month", exec_ui.people(um.value),
             f"range {exec_ui.people(um.low)} – {exec_ui.people(um.high)}", "unique"),
            (f"{cap(c.audience_short)} a month", exec_ui.people(r.profile.relevant_reach.value), "", "relevant"),
            ("Price level", dots(p.price_level), knowledge_mod.RATING_WORDS[p.price_level], "price"),
        ]
        for i in range(0, len(tiles), 2):
            for col, t in zip(st.columns(2), tiles[i:i + 2]):
                with col:
                    info_tile(*t, focus)
        st.caption("ⓘ Click a number's name to see the source behind it.")

    st.markdown("<div class='ooh-sec'>All locations</div>", unsafe_allow_html=True)
    st.caption("Every billboard with its viewing zone. Click a billboard to load it into the close-up above.")
    location_map(res, pcfg, params, focus, close=False, key="loc_city", height=420)
    faces = {f["id"]: f for f in face_rows(res, focus)}
    cols = st.columns(len(res.placements))
    for col, (pid, rr) in zip(cols, res.placements.items()):
        f, mm = faces[pid], rr.metrics
        with col, st.container(border=True):
            st.markdown(
                f"<div class='ooh-loc'><span class='dot' style='background:{f['color']}'></span><b>{f['label']}</b>"
                f"{' <span class=ooh-star>⭐ plan</span>' if f['in_plan'] else ''}"
                f"<div class='ooh-locsub'>{f['road']} · {f['type']} · price {dots(f['price_level'])}</div>"
                f"<div class='ooh-locnum'><b>{exec_ui.people(mm['impressions_day'].value)}</b> impressions / day<br/>"
                f"<b>{exec_ui.people(mm['unique_month'].value)}</b> people / month<br/>"
                f"<b>{exec_ui.people(rr.profile.relevant_reach.value)}</b> {c.audience_short}</div></div>",
                unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            if b1.button("Select", key=f"loc_sel_{pid}", width="stretch",
                         type="primary" if pid == focus else "secondary"):
                goto(focus=pid)
            if b2.button("Profile →", key=f"loc_aud_{pid}", width="stretch"):
                goto("Audience profile", pid)


# --------------------------------------------------------------------------- screen 2: numbers per location


def location_sources(res: Results, pcfg, params: Params, focus: str) -> None:
    """Data sources page, top: every number for the selected location and the source behind it."""
    name = name_of(res, focus)
    st.markdown(f"<div id='loc-numbers' class='ooh-sec'>③ Numbers for {html.escape(name)}, and the source behind "
                "each</div>", unsafe_allow_html=True)
    location_picker(res, focus, "src_pick")
    rows = location_numbers(res, pcfg, params, focus)
    groups = [g for g in NUM_GROUPS if any(x["group"] == g for x in rows)]
    shown = st.pills("Show", ["All"] + groups, default="All", key=f"src_grp_{focus}")
    sel_rows = [x for x in rows if shown in (None, "All") or x["group"] == shown]
    df = pd.DataFrame([{
        "Group": x["group"], "Number": x["title"], "Value": x["display"],
        "Label": exec_ui.ENGINE_TO_BRIEF.get(x["label"], x["label"]), "Source": x["source"],
        "Confidence": x["score"], "Link": x["url"] or None} for x in sel_rows])
    slot = st.container()
    ev = st.dataframe(df, hide_index=True, width="stretch", height=min(520, 38 + 35 * len(df)),
                      on_select="rerun", selection_mode="single-row", key=f"src_tbl_{focus}_{shown}",
                      column_config={
                          "Group": st.column_config.TextColumn("Group", width="small"),
                          "Number": st.column_config.TextColumn("Number", width="large"),
                          "Value": st.column_config.TextColumn("Value", width="medium"),
                          "Label": st.column_config.TextColumn("Label", width="small"),
                          "Source": st.column_config.TextColumn("Source", width="medium"),
                          "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0,
                                                                        max_value=100, format="%d", width="small"),
                          "Link": st.column_config.LinkColumn("Link", display_text="open ↗", width="small")})
    picked = (getattr(ev, "selection", None) or {}).get("rows", []) if ev else []
    with slot:
        if picked:
            st.markdown(source_card(sel_rows[picked[0]]), unsafe_allow_html=True)
        else:
            st.caption("☑️ Tick a row to see how the number is made, the exact figure or quote we took, and the "
                       "source behind it.")
    n_conf = sum(1 for x in rows if x["label"] == "VERIFIED")
    n_weak = sum(1 for x in rows if x["label"] in ("SAMPLE", "ASSUMPTION"))
    st.caption(f"{len(rows)} numbers for {name}: {n_conf} confirmed, {n_weak} on sample inputs or our assumptions "
               "(shown as ratings where we are unsure). Source confidence is explained at the bottom of this page.")


# --------------------------------------------------------------------------- screen 3: audience profile


def _bars(items: list[tuple[str, float, str]], vmax: float | None = None) -> str:
    vmax = vmax or max((v for _, v, _ in items), default=1) or 1
    return "".join(f"<div class='pb'><span class='pb-l'>{html.escape(k)}</span><span class='pb-t'>"
                   f"<span class='pb-b' style='width:{min(100, v / vmax * 100):.0f}%'></span></span>"
                   f"<span class='pb-v'>{t}</span></div>" for k, v, t in items)


def _block(title: str, body: str, note: str = "") -> None:
    st.markdown(f"<div class='pf-h'>{html.escape(title)}</div>{body}"
                + (f"<div class='pf-n'>{note}</div>" if note else ""), unsafe_allow_html=True)


def page_profile(res: Results, pcfg, params: Params, focus: str) -> None:
    c = pcfg.campaign
    r = res.placements[focus]
    m, prof, meta = r.metrics, r.profile, r.profile.meta or {}
    page_header("", "Audience profile", "")
    location_picker(res, focus, "prof_pick")
    N = _num_index(res, pcfg, params, focus)
    others = [i for i in res.placements if i != focus]
    with_whom = max(others, key=lambda i: res.overlap.loc[focus, i]) if others else None
    k1, k2, k3, k4 = st.columns(4)
    um = m["unique_month"]
    k1.metric("Unique people a month", exec_ui.people(um.value),
              help=f"Range {exec_ui.people(um.low)}–{exec_ui.people(um.high)} (estimate)")
    k2.metric(f"{cap(c.audience_short)} a month", exec_ui.people(prof.relevant_reach.value),
              help="Unique people × the share interested (Meta, sample until real values are loaded)")
    k3.metric("People a day", exec_ui.people(m["people_day"].value), help="Vehicles × people per vehicle")
    k4.metric("Most shared with", name_of(res, with_whom) if with_whom else "–",
              f"{exec_ui.people(res.overlap.loc[focus, with_whom])} people" if with_whom else None, delta_color="off")

    grid = st.columns(3, gap="medium")
    gender = meta.get("gender", {})
    with grid[0], st.container(border=True):
        _block("Gender", _bars([("Men", gender.get("male", 0), f"{gender.get('male', 0):.0%}"),
                                ("Women", gender.get("female", 0), f"{gender.get('female', 0):.0%}")], 1),
               "People within 1 km of the board")
        dsc = next((f for f in knowledge_facts(res, pcfg, params) if f.location == "all" and "dsc" in f.sources), None)
        how_we_know([N.get("gender"),
                     num_row("Audience", "dsc", "Dubai census check", dsc.display, dsc.trust, dsc.sources,
                             dsc.detail or "Official population mix, to sanity-check the Meta figures") if dsc else None])
    age = meta.get("age", {})
    with grid[1], st.container(border=True):
        _block("Age", _bars([(k, v, f"{v:.0%}") for k, v in age.items()]),
               f"Aged 25–54: {sum(v for k, v in age.items() if k in ('25-34', '35-44', '45-54')):.0%}")
        how_we_know([N.get("age")])
    interests = meta.get("interest_share", {})
    with grid[2], st.container(border=True):
        mine = c.meta_interest
        items = sorted(interests.items(), key=lambda kv: -kv[1])
        _block("Interests", _bars([(k.replace("_", " ").capitalize() + (" ★" if k == mine else ""), v, f"{v:.0%}")
                                   for k, v in items]),
               f"★ = the interest the {c.title} counts")
        how_we_know([N.get(f"interest_{k}") for k, _ in items])
    grid = st.columns(3, gap="medium")
    with grid[0], st.container(border=True):
        rush = knowledge_mod.rush_level(prof.commuter_share)
        _block("How and when they pass",
               _bars([("Drivers", road_share(r), f"{road_share(r):.0%}"),
                      ("Metro riders", 1 - road_share(r), f"{1 - road_share(r):.0%}")], 1)
               + f"<div class='pb'><span class='pb-l'>Rush-hour traffic</span>{dots(rush)} "
                 f"<span class='pb-v'>{knowledge_mod.RATING_WORDS[rush]}</span></div>",
               f"{N['metro']['display'] if 'metro' in N else ''}")
        how_we_know([N.get("road_share"), N.get("metro"), N.get("rush")])
    poi = {k: v for k, v in sorted(prof.poi_counts.items(), key=lambda kv: -kv[1])}
    with grid[1], st.container(border=True):
        _block("What is nearby (1 km)", _bars([(k.replace(" and ", " & "), v, f"{v:,.0f}") for k, v in poi.items()]),
               "Counted from OpenStreetMap")
        how_we_know([x for k, x in N.items() if k.startswith("poi_")])
    with grid[2], st.container(border=True):
        inc = N.get("premium")
        crowd = [x for x in N.values() if x["group"] == "In the news" and x["value"]]
        crowd = sorted(crowd, key=lambda x: -(x["value"] or 0))[:3]
        _block("Income and crowds",
               (f"<div class='pb'><span class='pb-l'>Income</span>{inc['display']}</div>" if inc else "")
               + "".join(f"<div class='pb'><span class='pb-l'>{html.escape(x['title'][:34])}</span>"
                         f"<span class='pb-v'>{html.escape(x['display'])}</span></div>" for x in crowd),
               "Crowd numbers read from news articles, each with its link")
        how_we_know([inc] + crowd)
    st.caption("Profiles are for the area around the board, never individuals. Meta figures are sample values until "
               "real ones are loaded. To compare two locations side by side, open Compare locations.")
    if st.button("⚖️ Compare this location with another →", key=f"prof_cmp_{focus}"):
        goto("Compare locations", focus)


# --------------------------------------------------------------------------- screen 4: compare two locations


def _compare_rows(res: Results, pcfg, params: Params, a: str, b: str) -> list[dict]:
    """Rows for the side-by-side table: (sector, title, value a, value b, text a, text b, better, source row)."""
    c = pcfg.campaign
    A, B = _num_index(res, pcfg, params, a), _num_index(res, pcfg, params, b)
    ra, rb = res.placements[a], res.placements[b]
    faces = {f["id"]: f for f in face_rows(res, a)}
    out = []

    def row(sector, title, va, vb, fmt, better=1, key=None, src=None):
        out.append({"sector": sector, "title": title, "a": va, "b": vb, "ta": fmt(va), "tb": fmt(vb),
                    "better": better, "src_a": (A.get(key) if key else None) or src,
                    "src_b": (B.get(key) if key else None) or src})

    P = exec_ui.people
    pct = lambda x: f"{x:.0%}"  # noqa: E731
    num = lambda x: f"{x:,.0f}"  # noqa: E731
    m = lambda r, k: r.metrics[k].value  # noqa: E731
    row("Traffic", "Vehicles a day", m(ra, "vehicles_day"), m(rb, "vehicles_day"), P, key="vehicles")
    row("Traffic", "People a day", m(ra, "people_day"), m(rb, "people_day"), P, key="people_day")
    row("Traffic", "Metro riders a day", (A.get("metro") or {}).get("value") or 0,
        (B.get("metro") or {}).get("value") or 0, P, key="metro")
    row("Visibility", "Seconds in view per pass", (A.get("dwell") or {}).get("value") or 0,
        (B.get("dwell") or {}).get("value") or 0, lambda x: f"{x:.0f} s", key="dwell")
    vis = lambda N, r: ((N.get("visibility") or {}).get("value") or r.metrics["mean_visibility"].value) * 100  # noqa: E731
    row("Visibility", "How well drivers see it (main road)", vis(A, ra), vis(B, rb), lambda x: f"{x:.0f} / 100",
        key="visibility")
    row("Reach", "Impressions a day", m(ra, "impressions_day"), m(rb, "impressions_day"), P, key="impressions_day")
    row("Reach", "Unique people a month", m(ra, "unique_month"), m(rb, "unique_month"), P, key="unique")
    row("Reach", f"{cap(c.audience_short)} a month", ra.profile.relevant_reach.value, rb.profile.relevant_reach.value,
        P, key="relevant")
    ga, gb = ra.profile.meta.get("gender", {}), rb.profile.meta.get("gender", {})
    row("Audience", "Men", ga.get("male", 0), gb.get("male", 0), pct, better=0, key="gender")
    aa, ab = ra.profile.meta.get("age", {}), rb.profile.meta.get("age", {})
    mid = ("25-34", "35-44", "45-54")
    row("Audience", "Aged 25–54", sum(aa.get(k, 0) for k in mid), sum(ab.get(k, 0) for k in mid), pct, better=0,
        key="age")
    ia, ib = ra.profile.meta.get("interest_share", {}), rb.profile.meta.get("interest_share", {})
    for k in sorted(set(ia) | set(ib), key=lambda k: (k != c.meta_interest, k)):
        row("Audience", f"Interested in {k.replace('_', ' ')}" + (" ★" if k == c.meta_interest else ""),
            ia.get(k, 0), ib.get(k, 0), pct, better=1 if k == c.meta_interest else 0, key=f"interest_{k}")
    row("Audience", "Drivers (vs metro riders)", road_share(ra), road_share(rb), pct, better=0,
        key="road_share")
    pa, pb = ra.profile.poi_counts, rb.profile.poi_counts
    place_cat, _ = profile_mod.CATEGORY_PLACES[profile_mod.category_key(c.brand_category)]
    for k in sorted(set(pa) | set(pb), key=lambda k: (k != place_cat, k)):
        key = "poi_" + k.lower().replace(" ", "-")
        row("Nearby (1 km)", k + (" ★" if k == place_cat else ""), pa.get(k, 0), pb.get(k, 0), num,
            better=1 if k == place_cat else 0, key=key)
    row("Board and ratings", "Plays delivered", (A.get("plays") or {}).get("value") or 0,
        (B.get("plays") or {}).get("value") or 0, lambda x: f"{x:.0%}" if x else "always on (static)", better=0,
        key="plays")
    row("Board and ratings", "Price level (our rating)", ra.prep.placement.price_level, rb.prep.placement.price_level,
        lambda x: knowledge_mod.rating(x), better=-1, key="price")
    row("Board and ratings", "Value for its price level", faces[a]["value_dots"], faces[b]["value_dots"],
        lambda x: knowledge_mod.rating(x), better=1)
    return out


def page_compare(res: Results, pcfg, params: Params, focus: str) -> None:
    c = pcfg.campaign
    page_header("", "Compare locations", "")
    ids = list(res.placements)
    facts = knowledge_facts(res, pcfg, params)
    pulse = footprint_mod.pulse_for_results(res, pcfg, c, params)
    scores = knowledge_mod.score_locations(res, pcfg, c, facts, pulse)["total"]
    rest = sorted([i for i in ids if i != focus], key=lambda i: -scores[i])
    l, r = st.columns(2, gap="medium")
    a = l.selectbox("Left", ids, index=ids.index(focus), key=f"cmp_a_{focus}", format_func=lambda i: name_of(res, i))
    if a != focus:
        goto(focus=a)
    b_default = st.session_state.get("cmp_b") if st.session_state.get("cmp_b") in ids else rest[0]
    b = r.selectbox("Right", ids, index=ids.index(b_default), key="cmp_b", format_func=lambda i: name_of(res, i))
    if a == b:
        st.info("Pick two different locations.")
        return
    with l:
        location_map(res, pcfg, params, a, close=True, key=f"cmp_map_a_{a}", height=230, clickable=False)
    with r:
        location_map(res, pcfg, params, b, close=True, key=f"cmp_map_b_{b}", height=230, clickable=False)

    rows = _compare_rows(res, pcfg, params, a, b)
    na, nb = name_of(res, a), name_of(res, b)
    wins = {a: [], b: []}
    for x in rows:
        if not x["better"] or x["a"] == x["b"]:
            continue
        hi = a if (x["a"] > x["b"]) == (x["better"] > 0) else b
        lo_v, hi_v = sorted([x["a"], x["b"]])
        ratio = hi_v / lo_v if lo_v else 9
        wins[hi].append((ratio, f"{x['title'].replace(' ★', '')} ({x['ta']} vs {x['tb']})" if hi == a
                         else f"{x['title'].replace(' ★', '')} ({x['tb']} vs {x['ta']})"))
    w1, w2 = st.columns(2, gap="medium")
    for col, pid, nm in ((w1, a, na), (w2, b, nb)):
        top = [t for _, t in sorted(wins[pid], key=lambda t: -t[0])[:4]]
        col.markdown(f"<div class='win'><div class='win-h'>Where {html.escape(nm)} wins</div>"
                     + ("<br/>".join(html.escape(t) for t in top) or "Nothing on the ranked rows")
                     + "</div>", unsafe_allow_html=True)

    shared = res.overlap.loc[a, b]
    body, sector = [], None
    for x in rows:
        if x["sector"] != sector:
            sector = x["sector"]
            body.append(f"<tr class='sec'><td colspan='3'>{html.escape(sector)}</td></tr>")
        ca = cb = ""
        if x["better"] and x["a"] != x["b"]:
            a_wins = (x["a"] > x["b"]) == (x["better"] > 0)
            ca, cb = ("best", "") if a_wins else ("", "best")
        src = x["src_a"]
        tag = (f"<span class='src-tag'>{html.escape(src['source'])} · "
               f"{html.escape(exec_ui.ENGINE_TO_BRIEF.get(src['label'], src['label']))}</span>") if src else ""
        body.append(f"<tr><td>{html.escape(x['title'])}{tag}</td><td class='{ca}'>{html.escape(x['ta'])}</td>"
                    f"<td class='{cb}'>{html.escape(x['tb'])}</td></tr>")
        if x["sector"] == "Reach" and x["title"].endswith("a month") and x["title"].startswith(cap(c.audience_short)):
            body.append(f"<tr><td>People who pass both</td><td colspan='2' style='text-align:center'>"
                        f"{exec_ui.people(shared)} shared · counted once in a plan</td></tr>")
    st.markdown(f"<table class='cmp-t cmp2'><tr><th>Sector</th><th>{html.escape(na)}</th><th>{html.escape(nb)}</th>"
                f"</tr>{''.join(body)}</table>", unsafe_allow_html=True)
    st.caption(f"Green = better for the {c.emoji} {c.title} · ★ = what this campaign counts · rows without colour "
               "describe, not rank.")

    drill = [x for x in rows if x["src_a"] or x["src_b"]]
    pick = st.selectbox("🔎 Drill into a row: how we know it, for both locations", [None] + list(range(len(drill))),
                        format_func=lambda i: "Pick a row…" if i is None else drill[i]["title"], key=f"cmp_drill_{a}_{b}")
    if pick is not None:
        d1, d2 = st.columns(2, gap="medium")
        for col, key, nm in ((d1, "src_a", na), (d2, "src_b", nb)):
            if drill[pick][key]:
                col.markdown(source_card(drill[pick][key], f"{nm} · "), unsafe_allow_html=True)

    st.markdown("<div class='ooh-sec'>Best plan</div>", unsafe_allow_html=True)
    st.caption(f"The brief books {c.boards} boards. Move the slider to see the best mix for any number of boards, "
               "or tap the cards to try your own.")
    faces = face_rows(res, focus)
    html_block(exec_ui.decision_html({"faces": faces, "trust": trust_of(*[f["label_trust"] for f in faces]),
                                      "aud_short": c.audience_short, **plan_options(res, c.boards)}), height=560)


# --------------------------------------------------------------------------- screen 5: campaign performance


def _activation(res: Results, pcfg, plan: list[str]) -> dict:
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "activation.yaml").read_text())
    q, a, pt = cfg["qr"], cfg["area_ads"], cfg["partner"]
    views = {i: res.placements[i].metrics["advertiser_impressions_month"].value for i in plan}
    scans = {i: v / 1e4 * q["scans_per_10k_views"] for i, v in views.items()}
    qr_visits = sum(scans.values()) * q["visit_share"]
    meta_aud = {i: float(np.mean([res.placements[i].profile.meta.get("audience_size_low", 0),
                                  res.placements[i].profile.meta.get("audience_size_high", 0)])) for i in plan}
    reached = sum(meta_aud.values()) * a["reach_share"]
    uniques = {i.id: i.unique for i in res.plan_items}
    passers = duplication.combined_unique(plan, uniques, res.overlap)
    consented = passers * pt["consented_share"]
    matched = consented * pt["match_share"]
    out = {"cfg": cfg, "scans": scans, "views": views, "qr_visits": qr_visits,
           "qr_actions": qr_visits * q["action_share"], "reached": reached,
           "ads_control": reached * a["control_action_rate"], "passers": passers, "consented": consented,
           "matched": matched, "v_control": matched * pt["control_visit_rate"]}
    out["ads_exposed"] = out["ads_control"] * (1 + a["lift"])
    out["v_exposed"] = out["v_control"] * (1 + pt["lift"])
    return out


def page_performance(res: Results, pcfg, params: Params, focus: str) -> None:
    c = pcfg.campaign
    page_header("", "Campaign performance", "")
    plan = [s.placement for s in res.plan] or list(res.placements)
    scope = st.segmented_control("Show", ["campaign"] + plan, default="campaign", key="perf_scope",
                                 format_func=lambda i: f"Whole campaign ({len(plan)} boards)" if i == "campaign"
                                 else name_of(res, i))
    ids = plan if scope in (None, "campaign") else [scope]
    st.warning("🧪 **Sample data.** Delivery uses sample play logs and simulated traffic; QR, Meta / Google and "
               "partner results apply example rates (config/activation.yaml) until live feeds are connected.")
    d = res.delivery[res.delivery["placement"].isin(ids)]
    planned, actual = float(d["planned"].sum()), float(d["actual"].sum())
    uniques = {i.id: i.unique for i in res.plan_items}
    reach = duplication.combined_unique(ids, uniques, res.overlap)
    target = duplication.combined_relevant(ids, res.plan_items, res.overlap)
    imp_month = sum(res.placements[i].metrics["impressions_month"].value for i in ids)
    freq = imp_month / reach if reach else 0
    pop_fact = next((f for f in knowledge_facts(res, pcfg, params) if f.location == "all" and "dsc" in f.sources), None)
    pop = float(pop_fact.value) if pop_fact and pop_fact.value and pop_fact.value > 1e5 else 3.8e6
    grps = reach / pop * 100 * freq
    imp_day = sum(res.placements[i].metrics["impressions_day"].value for i in ids)
    sov = (sum(res.placements[i].metrics["advertiser_impressions_day"].value for i in ids) / imp_day) if imp_day else 0
    reg = _registry()
    boards = [res.placements[i].prep.placement for i in ids]
    N = {i: _num_index(res, pcfg, params, i) for i in ids}
    play_vals = [N[i]["plays"]["value"] for i in ids if "plays" in N[i] and N[i]["plays"]["value"]]
    act = _activation(res, pcfg, ids)
    word = {"automotive": "test-drive bookings", "real_estate": "viewings booked",
            "retail": "offers redeemed"}.get(profile_mod.category_key(c.brand_category), "bookings")
    faces = {f["id"]: f for f in face_rows(res, focus)}

    def metric_row(title: str, tiles: list[tuple[str, str, str, str]]) -> None:
        st.markdown(f"<div class='ooh-sec'>{title}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='nt-grid4'>{''.join(num_tile(*t) for t in tiles)}</div>", unsafe_allow_html=True)

    metric_row("Delivery", [
        ("Views of our ad delivered", exec_ui.people(actual), "SAMPLE", f"of {exec_ui.people(planned)} planned"),
        ("Delivery index", f"{actual / planned:.0%}" if planned else "–", "SAMPLE", "delivered ÷ planned"),
        ("Plays delivered", f"{np.mean(play_vals):.0%}" if play_vals else "always on", "SAMPLE",
         "of booked plays (digital)"),
        ("Share of voice", f"{sov:.0%}", "VERIFIED", "our ad's share of all views (digital boards rotate 6 ads)")])
    metric_row("Reach", [
        ("Reach (unique people)", exec_ui.people(reach), "ESTIMATE", f"{reach / pop:.0%} of Dubai residents"),
        ("Frequency", f"{freq:.1f}", "ESTIMATE", "times each person passes"),
        ("GRPs", f"{grps:.0f}", "ESTIMATE", "reach % × frequency"),
        (f"{cap(c.audience_short)} reached", exec_ui.people(target), "ESTIMATE", "counted once across boards")])
    lvl = round(np.mean([p.price_level for p in boards]))
    val = round(np.mean([faces[i]["value_dots"] for i in ids]))
    fit = knowledge_mod.share_level(float(np.mean([res.placements[i].profile.interest_share.value for i in ids])))
    actions = act["qr_actions"] + act["ads_exposed"] - act["ads_control"]   # only what the boards caused
    metric_row("Efficiency (ratings, no money)", [
        ("Price level", dots(lvl), "ASSUMPTION", knowledge_mod.RATING_WORDS[lvl]),
        ("Value for its price level", dots(val), "ASSUMPTION", knowledge_mod.RATING_WORDS[val]),
        ("Audience fit", dots(fit), "ASSUMPTION", f"share who are {c.audience_short}"),
        (f"{cap(word)} per 10k {c.audience_short}", f"{actions / target * 1e4:.1f}" if target else "–", "SAMPLE",
         "caused by the boards")])
    metric_row("Response", [
        ("QR scans", exec_ui.people(sum(act["scans"].values())), "SAMPLE",
         f"{act['cfg']['qr']['scans_per_10k_views']:g} per 10k views of our ad"),
        ("Offer page visits", exec_ui.people(act["qr_visits"]), "SAMPLE", "from QR scans"),
        (cap(word), f"{actions:,.0f}", "SAMPLE", "caused by the boards: QR + extra from area ads"),
        ("Lift vs no billboard", f"+{act['cfg']['area_ads']['lift']:.0%}", "SAMPLE", "against a comparison area")])
    how_we_know([
        {"title": "Delivery", "display": f"{actual / planned:.0%}" if planned else "–", "label": "SAMPLE",
         "sources": [reg["playlog"] | {"id": "playlog"}, reg["rta"] | {"id": "rta"}],
         "detail": "Planned views of our ad vs delivered, week by week: traffic from the road model, plays from "
                   "the media owner's play log (sample until connected).", "quote": "", "url": ""},
        {"title": "Reach, frequency and GRPs", "display": f"{exec_ui.people(reach)} · {freq:.1f} · {grps:.0f}",
         "label": "ESTIMATE", "sources": [reg["rta"] | {"id": "rta"}, reg["assumptions"] | {"id": "assumptions"},
                                          reg["dsc"] | {"id": "dsc"}],
         "detail": "Reach = unique people across the boards, shared people counted once. Frequency = impressions "
                   "a month ÷ reach. GRPs = reach as a % of Dubai residents (Dubai Statistics Center) × frequency.",
         "quote": "", "url": ""},
        {"title": "Price level and value", "display": f"{knowledge_mod.rating(lvl)} · {knowledge_mod.rating(val)}",
         "label": "ASSUMPTION", "sources": [reg["inventory"] | {"id": "inventory"}],
         "detail": "Our 1-4 rating of each board's price against the others; value = target people per price "
                   "level, compared with the best board. No prices are used.", "quote": "", "url": ""},
        {"title": "Response", "display": f"{exec_ui.people(sum(act['scans'].values()))} scans", "label": "SAMPLE",
         "sources": [], "detail": "Example rates from config/activation.yaml applied to the views of our ad. Live "
                                  "sources once connected: Bitly (QR), Meta Ads Manager and Google Ads (area ads), "
                                  "the location partner's study.", "quote": "", "url": ""},
    ], "How we know: every metric on this page")

    g1, g2 = st.columns(2, gap="medium")
    with g1:
        wk = d.groupby("week", as_index=False)[["planned", "actual"]].sum()
        fig = go.Figure()
        fig.add_bar(x=wk["week"], y=wk["planned"], name="Planned", marker_color="#d9d6f3")
        fig.add_bar(x=wk["week"], y=wk["actual"], name="Delivered", marker_color=SERIES[0],
                    text=[f"{a / p:.0%}" if p else "" for a, p in zip(wk["actual"], wk["planned"])],
                    textposition="outside")
        fig.update_layout(**PLOT_LAYOUT, height=320, barmode="group", legend=LEGEND_TOP,
                          title_text="Views of our ad: planned vs delivered, by week", xaxis_title="Week")
        st.plotly_chart(fig, width="stretch")
    with g2:
        fig = go.Figure(go.Funnel(
            y=["Passed the boards", "Views of our ad", "Scanned the QR code", "Visited the offer page", cap(word)],
            x=[act["passers"], sum(act["views"].values()), sum(act["scans"].values()), act["qr_visits"],
               act["qr_actions"]],
            marker_color=[SERIES[0]] * 5, texttemplate="%{value:,.0f}", hovertemplate="%{y}: %{x:,.0f}<extra></extra>"))
        fig.update_layout(**PLOT_LAYOUT, height=320, showlegend=False, title_text="From seeing to acting (QR, sample)")
        st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='ooh-sec'>Re-engaging the people who passed</div>", unsafe_allow_html=True)
    cfg = act["cfg"]
    cards = [
        ("📱 QR code and short link", "Feasible today", "good", exec_ui.people(sum(act["scans"].values())),
         "scans in the month", f"{exec_ui.people(act['qr_visits'])} visits to the offer page, "
         f"{act['qr_actions']:,.0f} {word}. Counted per billboard, day and hour (Bitly)."),
        ("📣 Meta and Google area ads", "Feasible today", "good", f"+{cfg['area_ads']['lift']:.0%}",
         f"{word} vs comparison area", f"About {exec_ui.people(act['reached'])} people reached within "
         f"{cfg['area_ads']['radius_km']:g} km: {act['ads_exposed']:,.0f} {word} against {act['ads_control']:,.0f} "
         "expected without the billboard."),
        ("🎯 Specialist location partner", "Concept: needs a partner", "crit", exec_ui.people(act["matched"]),
         "passers-by reached on their phones", f"Of {exec_ui.people(act['passers'])} people who passed, "
         f"{cfg['partner']['consented_share']:.0%} share location with consent. Showroom visits: "
         f"{act['v_exposed']:,.0f} vs {act['v_control']:,.0f} in the control group (+{cfg['partner']['lift']:.0%})."),
    ]
    cols = st.columns(3)
    for col, (title, feas, kind, big, unit, text) in zip(cols, cards):
        with col, st.container(border=True):
            st.markdown(f"<div class='q-eb'>{title}</div><div class='q-a'>{big}</div><div class='q-q'>{unit}</div>"
                        f"<div class='q-t'>{text}</div><span class='q-chip {kind}'>{feas}</span> "
                        f"<span class='q-chip warn'>Sample</span>", unsafe_allow_html=True)
    st.caption("Measured against a comparison area with no ads. UAE Personal Data Protection Law: consented, grouped "
               "data only; Meta and Google target areas of about 1 km, not exact passers-by.")
    with st.expander("📦 Hand-off files for partners: booking sheet and viewing zones"):
        page_handoff(res, pcfg, params, embedded=True)


# --------------------------------------------------------------------------- the brief, answered


@st.cache_data(show_spinner=False)
def brief_cfg() -> dict:
    import yaml

    return yaml.safe_load((ROOT / "config" / "brief.yaml").read_text())


BRIEF_KEYS = ("interest_share", "fit_tilt")   # these follow the campaign, not the brief


def _brief_q(i: int, q: str, answer: str, text: str, label: str, kind: str, target: tuple) -> None:
    with st.container(border=True):
        st.markdown(f"<div class='q-eb'>Question {i}</div><div class='q-q'>{q}</div><div class='q-a'>{answer}</div>"
                    f"<div class='q-t'>{text}</div><span class='q-chip {kind}'>{label}</span>", unsafe_allow_html=True)
        if st.button("Show me →", key=f"brief_q{i}"):
            goto(*target)


def page_brief(pcfg_all, okey: tuple, road_rows: tuple, ekey: tuple, current) -> None:
    cfg = brief_cfg()
    pcfg = pcfg_all.with_campaign(cfg["campaign"])
    c = pcfg.campaign
    own = current.id == c.id
    key = okey if own else tuple((k, v) for k, v in okey if k not in BRIEF_KEYS)
    res = get_results(key, road_rows, ekey, ledger_stamp(), c.id)
    params = Params(build_cfg(road_rows), dict(key))
    acfg = params.cfg
    pid = cfg["placement"]
    r = res.placements[pid]
    p = r.prep.placement
    m = r.metrics
    aud = c.audience_short

    page_header(f"📋 The brief, answered · {c.emoji} {c.title}",
                "Can we measure a billboard on Sheikh Zayed Road, and act on it?",
                "The questions from the AI Solution Brief, answered by the live engine for its worked example: "
                f"the {c.title} in {c.plan_start:%B}, booking {c.boards} boards. Every "
                "number is computed now, and labelled the way the brief asks.")
    if not own:
        st.info(f"This page always answers the brief's example ({c.emoji} {c.title}). The campaign picker above "
                f"changes the other pages; the buttons below open them on the {c.title}.")
    moved = [k for k, v in key if k not in BRIEF_KEYS and abs(v - acfg.parameters[k].value) > 1e-12]
    if own:
        moved += [k for k in BRIEF_KEYS if k in dict(key) and abs(dict(key)[k] - (getattr(c, k) if getattr(c, k) is not None
                                                                                     else acfg.parameters[k].value)) > 1e-12]
    if moved or road_rows:
        st.warning("Analyst controls have moved (" + ", ".join(pname(k) for k in moved) + ("road table" if not moved
                   else "") + "), so these numbers differ from the document. Reset them under Analyst controls.")

    t_ans, t_real, t_path = st.tabs(["🎯 The answers", "🔍 What's real today", "🚀 Path to market"])
    faces = {f["id"]: f for f in face_rows(res, pid)}
    plan = [s.placement for s in res.plan]
    dedup = float(duplication.combined_relevant(plan, res.plan_items, res.overlap)) if plan else 0.0
    naive = sum(res.placements[i].profile.relevant_reach.value for i in plan)
    with t_ans:
        html_block(exec_ui.brief_html({"view": "answer", "campaign": {
            "title": c.title, "emoji": c.emoji, "when": f"{c.plan_start:%B %Y}", "boards": c.boards, "aud": aud},
            "plan": {"names": [name_of(res, i) for i in plan], "audience": dedup, "dup": naive - dedup,
                     "boards": [{"label": name_of(res, i), "color": faces[i]["color"]} for i in plan]}}), height=250)

        # the planner's questions (Section 4)
        uq = m["unique_month"]
        meta = r.profile.meta or {}
        age = meta.get("age", {})
        young = age.get("25-34", 0) + age.get("35-44", 0)
        male = meta.get("gender", {}).get("male", 0)
        offices = r.profile.poi_counts.get("Offices and business", 0)
        rel = r.profile.relevant_reach.value
        rows = []
        for i, x in res.placements.items():
            rows.append({"id": i, "label": x.prep.placement.label, "road": x.prep.placement.corridor,
                         "color": faces[i]["color"], "in_plan": i in plan, "imp": x.metrics["impressions_day"].value,
                         "uniq": x.metrics["unique_month"].value, "uniq_lo": x.metrics["unique_month"].low,
                         "uniq_hi": x.metrics["unique_month"].high, "rel": x.profile.relevant_reach.value,
                         "price_dots": faces[i]["price_dots"], "value_dots": faces[i]["value_dots"],
                         "value": faces[i]["value"]})
        best = max(rows, key=lambda x: x["value"])
        for x in rows:
            x["best"] = x is best
        by_uniq = sorted(rows, key=lambda x: -x["uniq"])
        by_val = sorted(rows, key=lambda x: -x["value"])
        me = next(x for x in rows if x["id"] == pid)
        u_rank, v_rank = by_uniq.index(me) + 1, by_val.index(me) + 1
        ordinal = {1: "largest", 2: "second-largest", 3: "third-largest", 4: "smallest"}
        weeks = res.delivery[(res.delivery["placement"] == pid) & (res.delivery["days"] >= 7)].reset_index(drop=True)
        low_w = weeks.loc[weeks["delivery_index"].idxmin()] if len(weeks) else None
        ev = [e for e in news_events(res, params) if pid in e["faces"]]
        ev_text = ""
        if ev:
            e, fx = ev[0], ev[0]["faces"][pid]
            ev_text = (f" A {e['type'].lower()} on {e['date']:%-d %B}, found in the news, cuts this site by about "
                       f"{abs(fx['day_change']):.0%} that day and {abs(fx['campaign']):.1%} over the month.")
        q = [
            ("What is the estimated unique monthly audience for this placement?",
             f"About {exec_ui.people(uq.value)} people",
             f"Range {exec_ui.people(uq.low)}–{exec_ui.people(uq.high)}, from about {exec_ui.people(m['impressions_day'].value)} "
             f"impressions a day at {p.label}, {road_short(p.corridor)}.",
             exec_ui.ENGINE_TO_BRIEF.get(uq.label, uq.label), "accent", ("Explore a location", pid, c.id)),
            ("What audience characteristics can reasonably be inferred?",
             f"{exec_ui.people(rel)} {aud}",
             f"About {young:.0%} aged 25–44 and {male:.0%} male; rush-hour traffic rated "
             f"{knowledge_mod.RATING_WORDS[knowledge_mod.rush_level(r.profile.commuter_share)].lower()}, with {offices} "
             "offices and businesses within 1 km.",
             "Sample figures until Meta values are loaded" if r.profile.meta_is_sample else "Estimate", "warn",
             ("Explore a location", pid, c.id)),
            ("How does the placement compare with alternative locations?",
             f"{ordinal.get(u_rank, '')} audience, #{v_rank} on value".capitalize(),
             (f"It reaches the most people of the {len(rows)} billboards"
              if u_rank == 1 else f"It ranks #{u_rank} of {len(rows)} on people reached")
             + (f", but has the highest price level, so the least {aud} for its price level "
                f"(value {knowledge_mod.rating(me['value_dots'])}; best: {best['label']})." if v_rank == len(rows) else
                f"; value {knowledge_mod.rating(me['value_dots'])} for its price level (best: {best['label']})."),
             "Estimate; price level is our rating", "accent", ("Score & compare", pid, c.id)),
            ("How can we estimate campaign delivery against the original plan?",
             "Weekly delivery index",
             (f"Delivered ÷ planned, per week and billboard: week {int(low_w['week'])} at {low_w['delivery_index']:.0%} of "
              "plan is flagged early." if low_w is not None and low_w["delivery_index"] < 0.95 else
              "Delivered ÷ planned, per week and billboard; weeks under 95% are flagged early.") + ev_text,
             "Simulated until traffic history and play logs are connected", "warn", ("Campaign health", pid, c.id)),
            ("Can the potentially exposed audience be re-engaged through digital media?",
             "Yes, in three steps",
             "QR codes and Meta / Google area ads work today; reaching the exact people who passed needs a specialist "
             "location partner (e.g. MEmob+, Azira) and user consent.", "Today + concept", "good",
             ("Hand off", pid, c.id)),
            ("Option A: what is the best combination across sites?",
             f"{len(plan)} boards: {', '.join(name_of(res, i) for i in plan)}",
             f"{', '.join(name_of(res, i) for i in plan)} reach {exec_ui.people(dedup)} {aud} after removing "
             f"{exec_ui.people(naive - dedup)} counted twice. Try other mixes on the Decision page.",
             "Estimate", "accent", ("Decision", pid, c.id)),
        ]
        for row in range(0, len(q), 2):
            cols = st.columns(2)
            for j, col in enumerate(cols):
                if row + j < len(q):
                    with col:
                        _brief_q(row + j + 1, *q[row + j])
        html_block(exec_ui.brief_html({"view": "table", "rows": rows, "aud_cap": cap(aud),
                                       "label_note": "Estimate", "legend": exec_ui.BRIEF_LABELS}), height=640)

    with t_real:
        reg = sources_mod.registry()
        srcs = sorted(reg, key=lambda s: -(s.potential - s.score))
        top = srcs[0].id if srcs else None
        counts = signals_mod.Ledger.load().counts()
        n_art = sum(counts.values())
        applied_events = len([e for e in res.events if e.get("status", "applied") == "applied"]) or len(res.events)
        ai_on = env_key("ANTHROPIC_API_KEY") is not None
        html_block(exec_ui.brief_html({
            "view": "real", "caps": cfg["capabilities"], "routes": cfg["activation"],
            "sources": [{"name": s.name, "status": s.status, "score": s.score, "potential": s.potential,
                         "top": s.id == top} for s in sorted(reg, key=lambda s: -s.potential)],
            "ai": [{"v": f"{n_art}", "k": "news articles read for road closures and events"},
                   {"v": f"{counts.get('rejected', 0)}", "k": "filtered out as noise, each with its reason"},
                   {"v": f"{applied_events}", "k": "road event applied to the forecast, linked to its source"},
                   {"v": "0", "k": "numbers invented by AI: every count comes from the location engine"}],
            "ai_note": ("Claude writes the audience summaries and reads local news; it never produces a count. "
                        + ("Claude is connected." if ai_on else "No Claude key is loaded right now, so summaries use "
                           "the template; the news ledger above was built earlier.")
                        + " Next: checking visibility from street photos; later: calibrating with mobile data."),
        }), height=1500)
        st.caption("Full detail: Data sources (with the data-flow diagram) and Check the data in the Analyst toolkit.")

    with t_path:
        html_block(exec_ui.brief_html({"view": "path", **{k: cfg[k] for k in (
            "roadmap", "roadmap_total", "costs", "maintenance", "risks", "value", "not_at_first")}}), height=1150)
        st.caption("Roadmap, options, risks and value are the plan from the AI Solution Brief response "
                   "(config/brief.yaml); they are not computed by the engine.")


# --------------------------------------------------------------------------- analyst toolkit: check, stress-test, hand off

WEAK_TRUST = ("SAMPLE", "ASSUMPTION", "CONCEPT")


@st.cache_resource(max_entries=12, show_spinner="Rebuilding the plan with every assumption at its low and high end...")
def get_stress(overrides: tuple, road_rows: tuple, event_overrides: tuple, stamp: str, campaign_id: str) -> pd.DataFrame:
    pcfg = load_placements().with_campaign(campaign_id)
    params = Params(build_cfg(road_rows), dict(overrides))
    res = get_results(overrides, road_rows, event_overrides, stamp, campaign_id)
    return stress_test(get_preps(), pcfg, params, events=res.events)


def weakest_source(f, reg: dict) -> str:
    """The source that limits a fact's trust: the lowest-scored one it relies on."""
    return min(f.sources, key=lambda s: reg[s].score if s in reg else 0)


def switched_off() -> tuple[int, int]:
    store = footprint_mod.PeopleStore.load()
    people_off = sum(1 for f in store.facts.values() if f.get("status") == "kept" and not f.get("enabled", True))
    road_off = sum(1 for v in st.session_state.get("event_overrides", {}).values() if not v)
    return people_off, road_off


def page_check(res: Results, pcfg, params: Params) -> None:
    c = pcfg.campaign
    st.header("Check the data")
    st.caption(f"Every fact the {c.emoji} {c.title} rests on, how solid it is and how to make it better. Switching a "
               "web-sourced number or a road event off changes the scores, the crowds and the forecast straight away.")
    facts = knowledge_facts(res, pcfg, params)
    picks = knowledge_mod.select(facts, c)
    used = [x for x in picks if x.used]
    weak = [x for x in used if x.fact.trust in WEAK_TRUST]
    reg = {s.id: s for s in sources_mod.registry()}
    people_off, road_off = switched_off()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Facts behind the {c.title}", f"{len(used)} of {len(picks)}",
              help="Facts that pass the relevance rule for this campaign (config/knowledge.yaml)")
    k2.metric("Measured or estimated", len(used) - len(weak))
    k3.metric("Placeholders or assumptions", len(weak), help="SAMPLE inputs, our assumptions and concepts")
    k4.metric("Switched off", people_off + road_off,
              help="Web-sourced numbers and road events turned off (see those two tabs)")

    t_weak, t_facts, t_web, t_road, t_src = st.tabs(
        ["🧩 Weakest links", "🧠 All facts", "🌐 Web-sourced numbers", "🚧 Road events", "📡 Sources"])
    with t_weak:
        groups: dict[str, list] = {}
        for x in weak:
            groups.setdefault(weakest_source(x.fact, reg), []).append(x)
        order = sorted(groups, key=lambda s: (-sum(x.fact.core for x in groups[s]), -len(groups[s])))
        if not order:
            st.success("Every fact this campaign uses is measured or estimated.")
        else:
            st.markdown(f"**{len(weak)}** of the {len(used)} facts behind this campaign are placeholders or assumptions. "
                        f"They come from **{len(order)}** sources; fix them in this order (most core numbers first).")
        for i, sid in enumerate(order, 1):
            xs, s = groups[sid], reg.get(sid)
            core = sum(x.fact.core for x in xs)
            trusts = sorted({x.fact.trust for x in xs})
            examples = ", ".join(dict.fromkeys(x.fact.title for x in xs))
            with st.container(border=True):
                st.markdown(
                    f"**{i}. {html.escape(s.name if s else sid)}** "
                    + " ".join(badge(t) for t in trusts)
                    + f" · {len(xs)} fact{'s' if len(xs) > 1 else ''} used"
                    + (f", **{core} core** (every plan rests on them)" if core else "")
                    + f"<br/><span style='color:#55536a;font-size:.88rem'>{html.escape(examples[:220])}"
                    + ("…" if len(examples) > 220 else "") + "</span>"
                    + (f"<br/>➜ <b>Fix:</b> {html.escape(s.upgrade)}" if s and s.upgrade else ""),
                    unsafe_allow_html=True)
    with t_facts:
        _facts_table(res, picks, reg)
    with t_web:
        _people_tab(res, pcfg, params)
    with t_road:
        _road_tab(res, pcfg, params)
    with t_src:
        _sources_table(facts, c, reg)


def _facts_table(res: Results, picks: list, reg: dict) -> None:
    c1, c2 = st.columns([1, 2])
    only = c1.segmented_control("Show", ["All", "Used", "Not used"], default="Used", key="kl_filter")
    where = c2.selectbox("Location", ["All locations"] + list(res.placements) + ["all"],
                         format_func=lambda i: {"All locations": "All locations", "all": "Dubai-wide"}.get(
                             i, name_of(res, i) if i in res.placements else i), key="kl_where")
    rows = []
    for x in picks:
        f = x.fact
        if (only == "Used" and not x.used) or (only == "Not used" and x.used):
            continue
        if where != "All locations" and f.location != where:
            continue
        ws = reg.get(weakest_source(f, reg))
        rows.append({"Used": x.used, "Relevance": x.score, "Why": x.reason,
                     "Location": name_of(res, f.location) if f.location in res.placements else "Dubai-wide",
                     "Topic": knowledge_mod.rules()["topics"][f.topic]["label"], "Fact": f.title, "Value": f.display,
                     "Trust": f.trust, "Sources": ", ".join(source_names().get(s, s) for s in f.sources),
                     "Feeds": ", ".join(sources_mod.OUTPUTS.get(o, o) for o in f.feeds) or "context only",
                     "How to improve": (ws.upgrade if ws and f.trust in WEAK_TRUST else ""), "Link": f.url or None})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=560, column_config={
        "Relevance": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
        "Link": st.column_config.LinkColumn(display_text="open ↗")})
    st.caption("Relevance = topic base + tag match + campaign window − weak figure; core numbers are always used; "
               "rules in config/knowledge.yaml. The flow diagram on the Overview is counted from this table.")


def _sources_table(facts: list, campaign, reg: dict) -> None:
    data = diagram_data()
    srcs = data["sources"]
    derived = {x["id"]: x for x in knowledge_mod.flow_graph(facts, campaign, list(reg.values()))["sources"]}
    live = sum(1 for x in srcs if x["status"] in ("live", "cached"))
    connected = sum(1 for x in srcs if x["status"] != "not connected")
    st.markdown(f"<span class='ooh-live'></span>**{live}** live or cached · **{connected}** of {len(srcs)} connected · "
                f"Claude: **{data['engine']['ai']['status']}**. Facts and feeds are counted from the knowledge layer.",
                unsafe_allow_html=True)
    df = pd.DataFrame([{
        "Source": x["name"], "Status": x["status"], "Confidence": x["score"], "Potential": x["potential"],
        "Facts": derived.get(x["id"], {}).get("facts", 0),
        "Used now": derived.get(x["id"], {}).get("used", 0),
        "Feeds": ", ".join(sources_mod.OUTPUTS.get(o, o) for o in derived.get(x["id"], {}).get("feeds", []))
                 or ("context only" if derived.get(x["id"], {}).get("facts") else "—"),
        "Upgrade": x["upgrade"], "Link": x["url"],
    } for x in sorted(srcs, key=lambda x: -x["score"])])
    st.dataframe(df, hide_index=True, width="stretch", height=460, column_config={
        "Confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100, format="%d"),
        "Potential": st.column_config.ProgressColumn("Potential once connected", min_value=0, max_value=100,
                                                     format="%d"),
        "Link": st.column_config.LinkColumn("Link")})
    with st.expander("How the confidence score works"):
        st.latex(r"\text{score} = 100 \times s \times (0.40\,p + 0.35\,d + 0.25\,f)")
        st.markdown(
            "- **p, provenance:** who stands behind the data (official 1.0, commercial 0.85, OpenStreetMap 0.75, "
            "model assumption 0.4).\n- **d, directness:** how directly it measures what we use it for.\n"
            "- **f, freshness:** live 1.0, cached within 30 days 0.85, static publication 0.6.\n"
            "- **s, status:** live, cached or configured 1.0; placeholder 0.35; not connected 0.\n\n"
            "A planning heuristic (ASSUMPTION); it never enters the reach calculation.")


def pname(key: str) -> str:
    """An assumption's name as its slider shows it."""
    return key.replace("_", " ").capitalize()


def _fmt_param(v: float, unit: str) -> str:
    num = f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}"
    return num if not unit or "0-1" in unit or "share" in unit else f"{num} {unit}"


def first_sentence(text: str) -> str:
    text = str(text or "")
    return text.split(". ")[0].rstrip(".") + "." if text else ""


def page_stress(res: Results, pcfg, params: Params, okey: tuple, road_rows: tuple, ekey: tuple) -> None:
    c = pcfg.campaign
    df = get_stress(okey, road_rows, ekey, ledger_stamp(), c.id)
    names = {pid: name_of(res, pid) for pid in res.placements}
    plans = lambda ids: ", ".join(names[i] for i in ids) or "no board"  # noqa: E731
    base_plan = df["base_plan"].iloc[0]
    st.header("Stress-test the pick")
    st.markdown(f"Our pick for the {c.emoji} **{c.title}**: **{plans(base_plan)}**. Below, every assumption is moved to "
                "the low and the high end of its range (the configured range, else ±25 %), one at a time, and the "
                "plan is rebuilt. The question: would we book different boards if we are wrong?")
    flips = df[~df["holds"]]
    n = len(df)
    if flips.empty:
        st.success(f"✅ **The pick holds** under all {n} assumptions.")
    else:
        st.warning(f"⚠️ **The pick holds under {n - len(flips)} of {n} tests.** It changes when:")
        for r in flips.itertuples():
            word = "below" if r.tip_side == "low" else "above"
            what = f"**{pname(r.parameter)}**"
            st.markdown(f"- {what} goes **{word} {_fmt_param(r.tip_value, r.unit)}** (now "
                        f"{_fmt_param(r.base, r.unit)}): the plan becomes **{plans(r.tip_plan)}**. "
                        f"<span style='color:#8a889c'>{html.escape(first_sentence(r.description))}</span>",
                        unsafe_allow_html=True)
        st.caption("A tipping point close to today's value means that number is worth checking before booking.")

    st.subheader("How many people the pick reaches, if we are wrong")
    top = df.sort_values("swing", ascending=False).head(8).iloc[::-1]
    base_aud = float(df["audience_base"].iloc[0])
    fig = go.Figure()
    lo = top[["audience_low", "audience_high"]].min(axis=1)
    hi = top[["audience_low", "audience_high"]].max(axis=1)
    fig.add_trace(go.Bar(y=top["parameter"].map(pname), x=hi - lo, base=lo, orientation="h", marker_color=SERIES[0],
                         customdata=np.stack([top["low"], top["high"], top["audience_low"], top["audience_high"]], 1),
                         hovertemplate="%{y}: %{customdata[0]:.3g} → %{customdata[1]:.3g}<br>"
                                       "audience %{customdata[2]:,.0f} → %{customdata[3]:,.0f}<extra></extra>"))
    fig.add_vline(x=base_aud, line_color="#1d1b2e", line_width=1, line_dash="dot")
    fig.update_layout(**PLOT_LAYOUT, height=380, showlegend=False,
                      title_text=f"{cap(c.audience_short)} reached a month by the pick (base {fmt_num(base_aud)})",
                      xaxis_title=f"{cap(c.audience_short)} / month")
    st.plotly_chart(fig, width="stretch")
    t0 = df.sort_values("swing", ascending=False).iloc[0]
    st.markdown(f"Whichever boards we book, the size of the audience is the bigger uncertainty: **{pname(t0['parameter'])}** alone "
                f"moves it from {fmt_num(min(t0['audience_low'], t0['audience_high']))} to "
                f"{fmt_num(max(t0['audience_low'], t0['audience_high']))}. That is the number to measure first "
                "(see *Check the data* for how).")
    with st.expander(f"All {n} tests"):
        st.dataframe(pd.DataFrame([{
            "Assumption": pname(r.parameter), "Group": r.group, "Low": _fmt_param(r.low, r.unit),
            "Now": _fmt_param(r.base, r.unit), "High": _fmt_param(r.high, r.unit),
            "Pick holds": "✅" if r.holds else "⚠️ changes",
            "Plan at low": plans(r.plan_low), "Plan at high": plans(r.plan_high),
            "Audience at low": r.audience_low, "Audience at high": r.audience_high,
        } for r in df.sort_values(["holds", "swing"], ascending=[True, False]).itertuples()]),
            hide_index=True, width="stretch", height=480, column_config={
                "Audience at low": st.column_config.NumberColumn(format="%,.0f"),
                "Audience at high": st.column_config.NumberColumn(format="%,.0f")})
        st.caption("One assumption at a time, others at today's values (including your slider changes). Move a "
                   "slider under Analyst controls to test a combination.")


def page_handoff(res: Results, pcfg, params: Params, embedded: bool = False) -> None:
    import json

    c = pcfg.campaign
    ids = [s.placement for s in res.plan]
    if not embedded:
        st.header("Hand off: book it, target it, track it")
        st.caption(f"What the media team needs once the {c.emoji} {c.title} pick is agreed.")

    st.subheader("1 · Book the boards")
    rows = []
    for pid in ids:
        r = res.placements[pid]
        p = r.prep.placement
        rows.append({"Location": p.label, "Board": p.name, "Road": p.corridor, "Format": p.type.title(),
                     "Size": f"{p.width_m:g} × {p.height_m:g} m",
                     "Our share of screen": f"1 in {round(1 / p.share_of_voice)}" if p.share_of_voice < 1 else "Always on",
                     "From": f"{c.plan_start:%d %b %Y}", "To": f"{c.plan_end:%d %b %Y}",
                     "Price level (our rating)": knowledge_mod.rating(p.price_level),
                     f"{cap(c.audience_short)} / month": round(r.profile.relevant_reach.value, -2)})
    book = pd.DataFrame(rows)
    st.dataframe(book, hide_index=True, width="stretch", column_config={
        f"{cap(c.audience_short)} / month": st.column_config.NumberColumn(format="%,.0f")})
    st.download_button("⬇️ Booking sheet (CSV)", book.to_csv(index=False), f"booking_{c.id}.csv", "text/csv")
    st.caption("Price level is our 1-4 rating of each board against the others; ask the media owner for quotes.")

    st.subheader("2 · Reach the same people on their phones (optional)")
    st.markdown("Ad platforms can show mobile ads to people who were near a board. They need each board's "
                "**viewing zone** as a file: that is what these downloads are (the coordinates are inside the files).")
    geo = json.loads(res.zones_geojson)
    geo["features"] = [f for f in geo["features"] if f["properties"].get("placement_id") in ids]
    radius = pd.read_csv(io.StringIO(res.radius_csv))
    radius = radius[radius["placement_id"].isin(ids)]
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Viewing zones (GeoJSON, for data partners)", json.dumps(geo), f"zones_{c.id}.geojson",
                       "application/geo+json", width="stretch")
    d2.download_button("⬇️ Centre + radius (CSV, for Meta / Google)", radius.to_csv(index=False),
                       f"radius_{c.id}.csv", "text/csv", width="stretch")
    st.caption(f"Platforms need at least a {PLATFORM_MIN_RADIUS_KM:g} km radius (ASSUMPTION; check each platform), "
               "so the circle also reaches people who never passed the board. Nothing is sent from this app.")
    with st.expander("Which route, and how to measure it"):
        st.dataframe(pd.DataFrame([
            ["Location data partner + DSP", "Partner (e.g. Blis, Azira) flags consented phones seen in the zone; the "
             "audience goes to DV360 or The Trade Desk", "High"],
            ["Platform radius targeting", "Meta, Google, Snap or TikTok target people in or near the zone", "Medium-low"],
            ["Synced digital OOH", "Mobile ads run nearby while the digital screen shows the creative", "Medium"],
        ], columns=["Route", "How it works", "Precision"]), hide_index=True, width="stretch")
        st.markdown("**Measuring it:** people who passed vs a matched group who never did: store, showroom or "
                    "sales-centre visits, site visits and bookings. Google Trends gives a free brand-search signal.")
        st.markdown("**Limits:** UAE data protection law (Decree-Law 45 of 2021): consented, aggregated data only. "
                    "iPhone users can refuse tracking. Platforms set minimum radius and audience sizes.")

    if embedded:
        return
    st.subheader("3 · Track delivery")
    st.markdown("Once the boards are live, **Campaign health** compares delivered with planned views per board and "
                "flags road events that change the forecast.")
    if st.button("📈 Open Campaign health"):
        goto("Campaign health")



def page_assumptions(res: Results, acfg: AssumptionConfig, params: Params) -> None:
    st.header("Assumptions and sources")
    st.markdown(" ".join(f"{badge(k)} {v}" for k, v in {
        "VERIFIED": "published by an official or named source",
        "ESTIMATE": "calculated from verified data plus a stated assumption",
        "ASSUMPTION": "a parameter we chose, editable in the sidebar",
        "SAMPLE": "placeholder input, not real data",
        "CONCEPT": "needs a partner or further validation"}.items()), unsafe_allow_html=True)
    rows = []
    for key, p in acfg.parameters.items():
        rows.append({"parameter": key, "current": params.base(key), "default": p.value,
                     "low": params.get(key, "low") if p.low is not None else None,
                     "high": params.get(key, "high") if p.high is not None else None,
                     "unit": p.unit, "label": p.label, "source": p.source, "link": p.source_url or "",
                     "description": p.description})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"link": st.column_config.LinkColumn("link")})
    st.subheader("Road classes")
    st.dataframe(pd.DataFrame([{"class": k, **v.model_dump()} for k, v in params.cfg.road_classes.items()]),
                 hide_index=True, width="stretch")
    st.caption("Motorway 5 / trunk 4 / primary 3 default lanes are from the solution design doc; utilisation "
               "factors and speeds are ASSUMPTIONS.")

    st.subheader("Data sources")
    st.dataframe(pd.DataFrame([{"source": x.name, "status": x.status, "confidence": x.score, "label": x.label,
                                "used for": ", ".join(sources_mod.OUTPUTS[o] for o in x.feeds), "link": x.url}
                               for x in sources_mod.registry()]),
                 hide_index=True, width="stretch",
                 column_config={"link": st.column_config.LinkColumn("link"),
                                "confidence": st.column_config.ProgressColumn("confidence", min_value=0,
                                                                              max_value=100, format="%d")})
    st.caption("Full detail, the scoring formula and the flow diagram are on the Data sources page.")

    st.subheader("Snapping log")
    st.dataframe(pd.DataFrame(res.snap_log), hide_index=True, width="stretch")
    st.caption("Each face is snapped to the nearest matching carriageway whose traffic flows towards it, then "
               "placed 15 m to the right of the carriageway centre line and turned to face oncoming traffic.")

    st.subheader("Known limits")
    st.markdown(
        "- Frequency and duplication are assumptions; unique reach can be off by 2x or more.\n"
        "- No public Sheikh Zayed Road daily count; volume is the RTA-capacity estimate.\n"
        "- Line of sight is 2D (OSM footprints); bridges, trees and other boards are missed.\n"
        "- Metro riders use the nearest station's ridership, not the line load past the face.\n"
        "- Meta, DSC, metro and play-log inputs are SAMPLE until real values are entered.")


# --------------------------------------------------------------------------- main


def main() -> None:
    acfg, pcfg_all = load_assumptions(), load_placements()
    st.markdown(MOTION_CSS, unsafe_allow_html=True)
    apply_pending()
    campaign, pid = context_bar(pcfg_all)
    pcfg = pcfg_all.with_campaign(campaign.id)
    page, overrides, road_rows, use_llm = sidebar(acfg, pcfg)
    okey = tuple(sorted(overrides.items()))
    ekey = tuple(sorted(st.session_state.get("event_overrides", {}).items()))
    results = get_results(okey, road_rows, ekey, ledger_stamp(), campaign.id)
    params = Params(build_cfg(road_rows), overrides)

    if page in CHECK_PAGES:
        analyst_tag()
    if page == "Locations":
        page_locations(results, pcfg, params, pid)
    elif page == "Audience profile":
        page_profile(results, pcfg, params, pid)
    elif page == "Compare locations":
        page_compare(results, pcfg, params, pid)
    elif page == "Campaign performance":
        page_performance(results, pcfg, params, pid)
    elif page == "The brief":
        page_brief(pcfg_all, okey, road_rows, ekey, campaign)
    elif page == "Overview":
        page_overview(results, pcfg, params, pid)
    elif page == "Explore a location":
        page_explore(results, pcfg, params, pid, use_llm)
    elif page == "Score & compare":
        page_score(results, pcfg, params, pid, okey, road_rows, ekey)
    elif page == "Decision":
        page_decision(results, pcfg, params, pid)
    elif page == "Campaign health":
        page_health(results, pcfg, params, pid)
    elif page == "Data sources":
        page_sources(results, pcfg, params, pid)
    elif page == "Map":
        page_map(results, params, pid, pcfg)
    elif page == "Placement detail":
        page_detail(results, pid, params, use_llm, pcfg.campaign.brand)
    elif page == "Duplication and plan":
        page_duplication(results, pcfg.campaign.boards)
    elif page == "Check the data":
        page_check(results, pcfg, params)
    elif page == "Stress-test the pick":
        page_stress(results, pcfg, params, okey, road_rows, ekey)
    elif page == "Hand off":
        page_handoff(results, pcfg, params)
    else:
        page_assumptions(results, acfg, params)


main()
