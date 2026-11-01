"""OOH Audience Intelligence: Streamlit dashboard for placements H1 to H4.

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import io
import sys
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
from ooh import narrative as narrative_mod  # noqa: E402
from ooh import signals as signals_mod  # noqa: E402
from ooh import sources as sources_mod  # noqa: E402
from ooh.brain_viz import brain_html, diagram_data  # noqa: E402
from ooh.activation import PLATFORM_MIN_RADIUS_KM  # noqa: E402
from ooh.config import (AssumptionConfig, Params, RoadClass, env_key, load_assumptions,  # noqa: E402
                        load_placements)
from ooh.geometry import cone_polygon_lonlat  # noqa: E402
from ooh.metrics import Metric, fmt_num  # noqa: E402
from ooh.pipeline import Results, compute, prepare, sensitivity  # noqa: E402

st.set_page_config(page_title="OOH Decision Room", page_icon="📍", layout="wide")

# Executive pages answer one decision each; the analyst toolkit keeps the full technical detail.
EXEC_PAGES = ["Decision", "Billboard league", "Audience", "Campaign health"]
ANALYST_PAGES = [
    "Map",
    "Placement detail",
    "Compare locations",
    "Duplication and plan",
    "Planned vs actual",
    "Sensitivity",
    "Area signals",
    "Activation",
    "Data sources",
    "Assumptions and sources",
]
PAGES = EXEC_PAGES + ANALYST_PAGES
PAGE_ICONS = {"Decision": "🎯", "Billboard league": "🏆", "Audience": "👥", "Campaign health": "📈", "Map": "🗺️",
              "Placement detail": "🔎", "Compare locations": "📊", "Duplication and plan": "🔁",
              "Planned vs actual": "📦", "Sensitivity": "🎚️", "Area signals": "📰", "Activation": "📲",
              "Data sources": "🧠", "Assumptions and sources": "📚"}
PID_PAGES = {"Map", "Placement detail", "Planned vs actual", "Sensitivity"}
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
def get_results(overrides: tuple, road_rows: tuple, event_overrides: tuple = (), stamp: str = "") -> Results:
    pcfg = load_placements()
    params = Params(build_cfg(road_rows), dict(overrides))
    return compute(get_preps(), pcfg, params, event_overrides=dict(event_overrides))


@st.cache_resource(max_entries=24, show_spinner="Running sensitivity...")
def get_sensitivity(pid: str, overrides: tuple, road_rows: tuple) -> pd.DataFrame:
    params = Params(build_cfg(road_rows), dict(overrides))
    return sensitivity(get_preps()[pid], params)


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
    return ", ".join(p.id for p in pcfg.placements if signals_mod.affects(ev, p, types)) or "none"


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
/* sidebar navigation */
[data-testid="stSidebar"] { border-right: 1px solid var(--ooh-line); }
.ooh-brand { display:flex; align-items:center; gap:10px; margin: 0 0 14px; }
.ooh-brand .logo { width:38px; height:38px; border-radius:12px; display:grid; place-items:center; font-size:20px;
                   background: linear-gradient(135deg, #8b7cf0, #6250d6); box-shadow: 0 6px 16px rgba(98,80,214,.3); }
.ooh-brand b { font-size: 1.05rem; color: var(--ooh-ink); display:block; line-height:1.2; }
.ooh-brand span { font-size: .8rem; color: var(--ooh-muted); }
[data-testid="stSidebar"] [role="radiogroup"] { gap: 2px; padding-top: 22px; position: relative; width: 100%; }
[data-testid="stSidebar"] [role="radiogroup"]::before { content: "DECIDE"; position:absolute; top:0; left:10px;
    font-size: 11px; font-weight: 800; letter-spacing: .1em; color: var(--ooh-muted); }
[data-testid="stSidebar"] [role="radiogroup"] > div { width: 100%; position: relative; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] { width: 100%; padding: 7px 10px; border-radius: 10px; margin: 0;
    cursor: pointer; transition: background .15s ease, transform .15s ease; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:not([data-testid="stMarkdownContainer"]) { display: none; }
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover { background: #efedfc; transform: translateX(3px); }
[data-testid="stSidebar"] [role="radiogroup"] > div[data-selected="true"] [data-testid="stRadioOption"] {
    background: #efedfc; box-shadow: inset 3px 0 0 #6250d6; }
[data-testid="stSidebar"] [role="radiogroup"] > div[data-selected="true"] p { font-weight: 700; color: #6250d6; }
[data-testid="stSidebar"] [role="radiogroup"] > div:nth-of-type(5) { margin-top: 30px; }
[data-testid="stSidebar"] [role="radiogroup"] > div:nth-of-type(5)::before { content: "ANALYST TOOLKIT"; position:absolute;
    top:-20px; left:10px; font-size: 11px; font-weight: 800; letter-spacing: .1em; color: var(--ooh-muted); }
[data-testid="stSidebar"] [role="radiogroup"] > div:nth-of-type(n+5) p { font-size: .9rem; }
[data-testid="stSidebar"] [role="radiogroup"] > div:nth-of-type(-n+4) p { font-size: 1rem; font-weight: 600; }
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


# --------------------------------------------------------------------------- UI helpers


def badge(label: str) -> str:
    fg, bg = BADGE_COLORS.get(label, ("#41464b", "#e2e3e5"))
    return (f"<span style='background:{bg};color:{fg};border-radius:4px;padding:1px 6px;"
            f"font-size:0.72rem;font-weight:600;letter-spacing:0.03em'>{label}</span>")


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


def v_color(v: float, vmax: float) -> list[int]:
    """Light blue (low visibility) to deep navy (high): one-hue sequential ramp for a light basemap."""
    t = 0.0 if vmax <= 0 else min(1.0, v / vmax)
    stops = [(0.0, (134, 182, 239)), (0.35, (57, 135, 229)), (0.7, (37, 106, 191)), (1.0, (13, 54, 107))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return [int(c0[i] + k * (c1[i] - c0[i])) for i in range(3)] + [235]
    return [13, 54, 107, 235]


def lonlat_path(geom) -> list[list[float]]:
    xs, ys = geom.xy
    lon, lat = _to_wgs.transform(np.asarray(xs), np.asarray(ys))
    return [[float(a), float(b)] for a, b in zip(lon, lat)]


# --------------------------------------------------------------------------- sidebar


def sidebar(acfg: AssumptionConfig, pcfg) -> tuple[str, str, dict, tuple, bool]:
    st.sidebar.markdown(
        f"<div class='ooh-brand'><div class='logo'>📍</div><div><b>OOH Decision Room</b>"
        f"<span>{pcfg.campaign.brand} · Dubai</span></div></div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Page", PAGES, key="page", label_visibility="collapsed",
                            format_func=lambda x: f"{PAGE_ICONS.get(x, '')}\u2002{x}")
    ids = [p.id for p in pcfg.placements]
    keep = st.session_state.get("pid_keep", ids[0])
    if page in PID_PAGES:
        pid = st.sidebar.selectbox("Billboard", ids, index=ids.index(keep) if keep in ids else 0,
                                   format_func=lambda i: f"{i} · {next(p.name for p in pcfg.placements if p.id == i)}",
                                   key="pid")
        st.session_state["pid_keep"] = pid
    else:
        pid = keep if keep in ids else ids[0]

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
        if abs(value - p.value) > 1e-12:
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
    if overrides or road_rows:
        st.sidebar.warning(f"{len(overrides) + (1 if road_rows else 0)} assumption(s) changed from the defaults.")
    return page, pid, overrides, road_rows, use_llm


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
    worst = max(labels, key=lambda l: ["VERIFIED", "ESTIMATE", "ASSUMPTION", "SAMPLE", "CONCEPT"].index(l)
                if l in exec_ui.TRUST else 1)
    return list(exec_ui.TRUST.get(worst, ("Estimate", "")))


def face_rows(res: Results) -> list[dict]:
    """One row per billboard, in config order, with the numbers the executive pages use."""
    plan_ids = {s.placement for s in res.plan}
    rows = []
    for i, (pid, r) in enumerate(res.placements.items()):
        p, rr = r.prep.placement, r.profile.relevant_reach
        rows.append({"id": pid, "name": p.name, "area": p.area.split(" / ")[0], "area_full": p.area,
                     "type": p.type.title(), "cost": float(p.cost_per_month_aed), "rel": float(rr.value),
                     "rel_lo": float(rr.low), "rel_hi": float(rr.high),
                     "cpp": float(p.cost_per_month_aed / rr.value) if rr.value else 0.0,
                     "color": exec_ui.FACE_COLORS[i % len(exec_ui.FACE_COLORS)], "in_plan": pid in plan_ids,
                     "label": rr.label, "sov": float(p.share_of_voice), "unique": float(r.metrics["unique_month"].value)})
    return rows


def plan_options(res: Results, budget: float, step: int = 10_000) -> dict:
    """De-duplicated relevant reach for every mix of billboards, and the plan builder's pick at each budget."""
    items, mat = res.plan_items, res.overlap
    ids = [it.id for it in items]
    subsets = {}
    for k in range(1, len(ids) + 1):
        for combo in combinations(ids, k):
            subsets[",".join(sorted(combo))] = {"rel": float(duplication.combined_relevant(list(combo), items, mat))}
    total = sum(it.cost_aed for it in items)
    top = int(np.ceil(max(budget * 1.5, total + step * 5) / step) * step)
    picks = {str(b): [s.placement for s in duplication.greedy_plan(items, mat, b)] for b in range(0, top + 1, step)}
    return {"subsets": subsets, "picks": picks, "budget_max": top, "step": step,
            "budget": int(round(budget / step) * step)}


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
                    "faces": hit["faces"],
                    "source": e.get("source", "")})
    return sorted(out, key=lambda x: x["date"])


def delivery_summary(res: Results) -> pd.DataFrame:
    g = res.delivery.groupby("placement").agg(planned=("planned", "sum"), forecast=("forecast", "sum"),
                                              actual=("actual", "sum"))
    g["index"] = g["actual"] / g["planned"]
    g["news"] = g["forecast"] / g["planned"] - 1
    return g


def page_decision(res: Results, pcfg, params: Params) -> None:
    budget = float(pcfg.campaign.budget_aed)
    faces = face_rows(res)
    by_id = {f["id"]: f for f in faces}
    opts = plan_options(res, budget)
    trust = trust_of(*[f["label"] for f in faces])
    start = pcfg.campaign.plan_start
    page_header(f"🎯 The decision · {pcfg.campaign.brand} · {start:%B %Y}",
                f"Where should our {exec_ui.aed(budget)} a month go?",
                f"We scored {len(faces)} billboards on how many car-interested people each one reaches per dirham, "
                "without counting the same driver twice. Here is the mix we recommend. Tap the cards to try your own.")
    html_block(exec_ui.decision_html({"faces": faces, "trust": trust, **opts}), height=560)

    # Three answers a board member asks next, plus the obvious "why not the flagship?"
    plan_ids = [s.placement for s in res.plan]
    deliv = delivery_summary(res)
    scope = [i for i in plan_ids if i in deliv.index] or list(deliv.index)
    d = deliv.loc[scope]
    expected = float(d["actual"].sum() / d["planned"].sum()) if d["planned"].sum() else 1.0
    status = ("Looks on track", "good") if expected >= 0.97 else ("Keep an eye on it", "warn") if expected >= 0.9 else \
        ("Likely behind plan", "crit")
    light = [pid for pid, r in d.iterrows() if r["index"] < 0.97]
    started = date.today() > pcfg.campaign.plan_start
    events = news_events(res, params)
    plan_rel = [f for f in faces if f["in_plan"]] or faces
    lo_x = sum(f["rel_lo"] for f in plan_rel) / sum(f["rel"] for f in plan_rel)
    hi_x = sum(f["rel_hi"] for f in plan_rel) / sum(f["rel"] for f in plan_rel)
    meter = {"VERIFIED": 5, "ESTIMATE": 3, "ASSUMPTION": 2, "SAMPLE": 2, "CONCEPT": 1}
    worst = max((f["label"] for f in faces), key=lambda l: meter.get(l, 3) * -1)
    tiles = [
        {"emoji": "📦", "q": "Will it deliver?", "a": f"{expected:.0%}", "unit": "of planned views expected",
         "text": ((f"For our pick ({', '.join(scope)}), " if plan_ids else "Across all billboards, ")
                  + ("based on a simulated month: no media-owner play logs or live traffic counts are connected yet. "
                     if not started else "simulated until play logs and live counts are connected. ")
                  + (f"{', '.join(light)} may run a little light." if light else "Every board is at or above plan.")),
         "chips": [(f"{'✅' if status[1] == 'good' else '👀' if status[1] == 'warn' else '🔴'} {status[0]}", status[1]),
                   ("Simulated", "warn")]},
    ]
    hits_plan = [(e, {k: v for k, v in e["faces"].items() if k in plan_ids}) for e in events]
    hits_plan = [(e, f) for e, f in hits_plan if f]
    others = sorted({k for e in events for k in e["faces"] if k not in plan_ids})
    if hits_plan:
        e, fs = hits_plan[0]
        worst_face = min(fs.items(), key=lambda kv: kv[1]["delta"])
        small = abs(worst_face[1]["campaign"]) < 0.02
        tiles.append({"emoji": "🚧", "q": "Anything in the way?",
                      "a": f"{len(hits_plan)} road event{'s' if len(hits_plan) > 1 else ''}", "unit": "for our pick",
                      "text": (f"<b>{e['date']:%a %d %b}</b>: {e['note'] or e['type']}. "
                               f"{worst_face[0]} loses about {exec_ui.people(abs(worst_face[1]['delta']))} views of our "
                               f"ad that day ({worst_face[1]['campaign']:+.1%} over the month)."),
                      "chips": [("Small effect" if small else "Material effect", "good" if small else "warn"),
                                ("From news headlines", "accent")]})
    else:
        tiles.append({"emoji": "🌤️", "q": "Anything in the way?", "a": "All clear", "unit": "for our pick",
                      "text": ("No closures, roadworks or big events are expected near the boards we recommend this month."
                               + (f" The only one found affects {', '.join(others)}, which is not in our pick."
                                  if others else "")),
                      "chips": [("From news headlines", "accent")]})
    tiles.append({"emoji": "🔍", "q": "How sure are we?", "a": trust[0], "unit": "", "meter": meter.get(worst, 3),
                  "text": (f"Good for ranking the billboards; treat the head counts as a range. Reach could land between "
                           f"{lo_x:.1f}× and {hi_x:.1f}× our central figure, mostly depending on how often the same "
                           "people repeat the trip. Traffic is estimated from road capacity, not live counters."),
                  "chips": [("Ranking: reliable", "good"), ("Head counts: ± a lot", "warn")]})

    why = None
    left_out = [f for f in faces if f["id"] not in plan_ids]
    if plan_ids and left_out:
        f = max(left_out, key=lambda x: x["rel"])
        best = min(faces, key=lambda x: x["cpp"])
        key_plan = ",".join(sorted(plan_ids))
        key_with = ",".join(sorted(plan_ids + [f["id"]]))
        inc = opts["subsets"][key_with]["rel"] - opts["subsets"][key_plan]["rel"]
        spent = sum(by_id[i]["cost"] for i in plan_ids)
        points = []
        if f["cpp"] >= max(x["cpp"] for x in faces) - 1e-9:
            points.append(f"<b>Priciest per person:</b> AED {f['cpp']:.2f} for each car-interested person, against "
                          f"AED {best['cpp']:.2f} for {best['id']}, the best value.")
        else:
            points.append(f"<b>Cost per person:</b> AED {f['cpp']:.2f}, against AED {best['cpp']:.2f} for {best['id']}.")
        mat = res.overlap
        partner = max(plan_ids, key=lambda x: mat.loc[f["id"], x] / min(mat.loc[f["id"], f["id"]], mat.loc[x, x]))
        share = mat.loc[f["id"], partner] / min(mat.loc[f["id"], f["id"]], mat.loc[partner, partner])
        rule = str(res.overlap_rules.loc[f["id"], partner])
        smaller = partner if mat.loc[partner, partner] <= mat.loc[f["id"], f["id"]] else f["id"]
        other = f["id"] if smaller == partner else partner
        if share >= 0.2:
            points.append(f"<b>Same drivers:</b> about {share:.0%} of the people who pass {smaller} also pass {other}"
                          f"{' (same road, same direction)' if 'same corridor' in rule else ''}, so much of its audience "
                          "is already covered.")
        need = spent + f["cost"] - budget
        points.append(f"<b>Small gain:</b> adding it would bring only {exec_ui.people(inc)} extra people for "
                      f"{exec_ui.aed(f['cost'])} a month (AED {f['cost'] / max(inc, 1):.2f} per extra person)"
                      + (f", and the budget would need to grow by {exec_ui.aed(need)}." if need > 0 else "."))
        why = {"title": f"Why isn't {f['id']} ({f['name']}) in the plan?", "points": points}
    html_block(exec_ui.insights_html({"tiles": tiles, "why": why}), height=470)
    st.caption("Head counts are people per month, counted once even if they pass several times. "
               "\"Car-interested\" = share of the audience with an interest in cars or SUVs. "
               "Billboard prices are planning assumptions until media-owner quotes arrive. "
               "Full method in the Analyst toolkit.")


def page_league(res: Results) -> None:
    faces = face_rows(res)
    page_header("🏆 Billboard league", "Which billboard gives us the most for the money?",
                "Each billboard on its own: price, audience and cost per car-interested person. "
                "Re-sort to see who wins on value, size or price.")
    best_cpp = min(f["cpp"] for f in faces)
    max_rel = max(f["rel"] for f in faces)
    max_cpp = max(f["cpp"] for f in faces)
    rows = []
    for f in faces:
        tags = [("⭐ In our plan", "accent") if f["in_plan"] else ("Not in plan", "")]
        if f["cpp"] == best_cpp:
            tags.append(("💎 Best value", "good"))
        if f["rel"] == max_rel:
            tags.append(("📣 Biggest audience", ""))
        if f["cpp"] == max_cpp and len(faces) > 1:
            tags.append(("💸 Priciest per person", "warn"))
        slots = round(1 / f["sov"]) if f["sov"] else 1
        rows.append({**f, "name": f"{f['name']} · {f['area_full']}", "tags": tags,
                     "type_note": (f"Digital screen · our ad is 1 of {slots} in rotation" if f["type"] == "Digital"
                                   and slots > 1 else f"{f['type']} · our ad shows all day"),
                     "cpp_note": "best value" if f["cpp"] == best_cpp else f"{f['cpp'] / best_cpp - 1:+.0%} vs best"})
    note = ("Car-interested people = unique people passing each month × the share interested in cars. "
            "The bar shows our central figure; the faint band is the likely range. Two billboards on the same road "
            "share many drivers, which is why the Decision page does not simply add them up.")
    html_block(exec_ui.league_html({"rows": rows, "trust": trust_of(*[f["label"] for f in faces]), "note": note}),
               height=600)


def page_audience(res: Results) -> None:
    faces = face_rows(res)
    page_header("👥 Audience", "Who will see our ad, and when?",
                "Use this to brief the creative and, on digital screens, to schedule it. ⭐ marks billboards in our plan.")
    out = []
    for f in sorted(faces, key=lambda x: (not x["in_plan"], -x["rel"])):
        r = res.placements[f["id"]]
        prof, meta = r.profile, r.profile.meta
        age = meta.get("age", {})
        male = float(meta.get("gender", {}).get("male", 0.5))
        core = sum(v for k, v in age.items() if k in ("25-34", "35-44", "45-54"))
        premium = any("premium" in s for s in prof.segments.get("Demographic", []))
        cars = int(prof.poi_counts.get("Car showrooms and services", 0))
        top_poi = [k.lower() for k, v in sorted(prof.poi_counts.items(), key=lambda kv: -kv[1])[:2] if v]
        hourly = [float(x) for x in r.reach.scenarios["base"].hourly_impressions]
        rush = sum(hourly[7:10] + hourly[17:20]) / sum(hourly) if sum(hourly) else 0
        share = prof.interest_share.value
        tenths = round(core * 10)
        if f["type"] == "Digital":
            sowhat = (f"<b>So what:</b> this is a digital screen, so we can choose when to run. Weight the SUV creative to "
                      f"the 7–10 am and 5–8 pm rush, when {rush:.0%} of views happen. Our ad shares the screen with "
                      f"{round(1 / f['sov']) - 1} others, so keep it to one image and one line.")
        else:
            sowhat = (f"<b>So what:</b> a static board shows one message all day to drivers at motorway speed. "
                      f"Design for a two-second glance: the car, the brand and one line.")
        if cars >= 10:
            sowhat += f" With {cars} car showrooms and services within 1 km, a 'test drive nearby' call to action fits."
        out.append({
            "id": f["id"], "area": f["area"], "color": f["color"], "in_plan": f["in_plan"], "type": f["type"],
            "avatar": "💼" if premium else "🚙",
            "headline": f"{'Premium-area' if premium else 'Everyday'} commuters through {f['area_full']}",
            "blurb": (f"{tenths} in 10 are aged 25–54 and {male:.0%} are men. Nearly all of them are in cars "
                      f"(the view count is road traffic){', plus a few metro riders' if r.reach.metro else ''}. "
                      + (f"Around the board you mostly find {' and '.join(top_poi)}." if top_poi else "")),
            "stats": [["🎯", f"{tenths} in 10", "aged 25–54"],
                      ["🚗", f"{exec_ui.people(f['rel'])}", f"car-interested people a month ({share:.0%} of the audience)"],
                      ["⏰", f"{rush:.0%}", "of views in the two rush hours"],
                      ["🏬", f"{cars}", "car showrooms and services within 1 km"]],
            "hourly": hourly, "age": {k.replace("-", "–"): float(v) for k, v in age.items()}, "male": male,
            "sowhat": sowhat})
    html_block(exec_ui.audience_html({"faces": out}), height=760)
    label = "SAMPLE" if any(res.placements[f["id"]].profile.meta_is_sample for f in faces) else "ESTIMATE"
    st.caption(f"Age, gender and car interest come from Meta audience estimates ({exec_ui.TRUST[label][0].lower()}: "
               f"{exec_ui.TRUST[label][1].lower()}). Hourly shape is a standard Dubai commuter curve (assumption). "
               "Nearby places are from OpenStreetMap.")


def page_health(res: Results, pcfg, params: Params) -> None:
    faces = face_rows(res)
    c = pcfg.campaign
    page_header("📈 Campaign health", "Is the campaign delivering what we paid for?",
                f"Campaign {c.plan_start:%d %b} – {c.plan_end:%d %b %Y}. Views delivered against the plan for each "
                "billboard (⭐ = in our pick), and anything on the roads that changes the forecast.")
    g = delivery_summary(res)
    rows = []
    for f in faces:
        if f["id"] not in g.index:
            continue
        r = g.loc[f["id"]]
        weeks = res.delivery[res.delivery["placement"] == f["id"]]["delivery_index"].astype(float).tolist()
        rows.append({"id": f["id"], "area": f["area"], "color": f["color"], "index": float(r["index"]), "in_plan": f["in_plan"],
                     "planned": float(r["planned"]), "actual": float(r["actual"]), "news": float(r["news"]),
                     "news_views": float(r["forecast"] - r["planned"]), "weeks": weeks})
    events = []
    for e in news_events(res, params):
        chips = [(f"{pid}: {v['day_change']:+.0%} that day · {exec_ui.people(abs(v['delta']))} views", "crit")
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
                 "can switch each one on or off under Area signals. Views = advertiser impressions (our slot only).")}),
        height=640)


# --------------------------------------------------------------------------- analyst pages


def page_map(res: Results, params: Params, pid: str) -> None:
    st.header("Placements, exposure cones and visible road segments")
    view_mode = st.radio("View", ["All placements", "Selected placement (sidebar)"], horizontal=True,
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
                    "tooltip": (f"<b>{p.id} · {row.label}</b> ({row.highway})<br/>V = {row.V:.3f} = "
                                f"D {row.D:.2f} × A {row.A:.2f} × O {row.O:.2f} × S {row.S:.2f} × T {row.T:.2f}"
                                f"<br/>{row.dist_m:.0f} m from face · {row.lanes} lanes ({row.lanes_source})"
                                f"<br/>Flow volume {vol:,.0f} vehicles/day · capacity fallback (ESTIMATE)"
                                f"{'<br/>Line of sight crosses a building' if row.blocked else ''}"),
                })
        if not r.metro_scored.empty:
            for row in r.metro_scored[r.metro_scored["included"]].itertuples():
                metro_rows.append({"path": lonlat_path(row.geometry),
                                   "tooltip": f"<b>{p.id} · metro track</b><br/>V = {row.V:.3f}"})
        cone_rows.append({"polygon": cone_polygon_lonlat(s.lon, s.lat, s.facing_bearing_deg, radius, half),
                          "tooltip": f"<b>{p.id} exposure cone</b><br/>radius {radius:.0f} m · half-angle {half:.0f}°"})
        u = r.metrics["unique_month"]
        pin_rows.append({"position": [s.lon, s.lat], "label": p.id,
                         "tooltip": (f"<b>{p.id} · {p.name}</b><br/>{p.type}, {p.width_m:g} × {p.height_m:g} m, "
                                     f"facing {s.facing_bearing_deg:.0f}°<br/>Unique / month {fmt_num(u.value)} "
                                     f"({fmt_num(u.low)}–{fmt_num(u.high)}) {u.label}<br/>Snapped to {s.road_name} "
                                     f"({s.snap_distance_m:.0f} m)")})
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
    st.caption("Basemap © CARTO, data © OpenStreetMap contributors. Switch to 'Selected placement' to zoom "
               "into the face picked in the sidebar.")
    rows = []
    for r in res.placements.values():
        s, p = r.prep.snapped, r.prep.placement
        rows.append({"id": p.id, "name": p.name, "lat": s.lat, "lon": s.lon, "facing °": s.facing_bearing_deg,
                     "snapped to": s.road_name, "snap distance m": s.snap_distance_m,
                     "visible segments": int(r.scored["included"].sum()) if not r.scored.empty else 0,
                     "OSM data": r.prep.area_source})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def page_detail(res: Results, pid: str, params: Params, use_llm: bool, brand: str) -> None:
    r = res.placements[pid]
    p, s, m, prof = r.prep.placement, r.prep.snapped, r.metrics, r.profile
    st.header(f"{p.id} · {p.name}")
    st.markdown(f"{p.type.title()} face, {p.width_m:g} × {p.height_m:g} m, facing {s.facing_bearing_deg:.0f}° "
                f"towards traffic on {s.road_name}. Share of voice {p.share_of_voice:.2f}. "
                f"Example brief: {brand}.")

    kpi_strip([
        ("Impressions / day", m["impressions_day"].value, "", m["impressions_day"].label),
        ("Unique people / month", m["unique_month"].value, "", m["unique_month"].label),
        ("Car-relevant / month", prof.relevant_reach.value, "", prof.relevant_reach.label),
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
         f"Ranks {pos} of {len(rank)} on car-relevant reach ({fmt_num(rr.value)} people/month); see Compare",
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
        metric_card("Car-relevant people", prof.relevant_reach, "/month")
    if p.type == "digital":
        metric_card(f"Advertiser impressions (one slot, SOV {p.share_of_voice:.2f})",
                    m["advertiser_impressions_day"], "/day")

    stages = [("Vehicles / day", m["vehicles_day"]), ("People / day", m["people_day"]),
              ("Visible impressions / day", m["impressions_day"]),
              ("Impressions / month", m["impressions_month"]), ("Unique people / month", m["unique_month"]),
              ("Car-relevant / month", prof.relevant_reach)]
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


def page_compare(res: Results) -> None:
    st.header("Compare locations")
    rows = []
    for r in res.placements.values():
        p, m, prof = r.prep.placement, r.metrics, r.profile
        adv, share = m["advertiser_impressions_month"], prof.interest_share.value

        def cpm_of(imp: float) -> float:
            return p.cost_per_month_aed / (imp * share / 1000) if imp * share else np.nan

        cpm, cpm_lo, cpm_hi = cpm_of(adv.value), cpm_of(adv.high), cpm_of(adv.low)  # more impressions -> lower cost
        rows.append({
            "Placement": f"{p.id} {p.area}", "Type": p.type,
            "Daily impressions (placement)": m["impressions_day"].value,
            "Daily impressions range": f"{fmt_num(m['impressions_day'].low)}–{fmt_num(m['impressions_day'].high)}",
            "Daily impressions (advertiser)": m["advertiser_impressions_day"].value,
            "Unique / month": m["unique_month"].value,
            "Unique range": f"{fmt_num(m['unique_month'].low)}–{fmt_num(m['unique_month'].high)}",
            "Car-relevant / month": prof.relevant_reach.value,
            "Car-relevant range": f"{fmt_num(prof.relevant_reach.low)}–{fmt_num(prof.relevant_reach.high)}",
            "Cost / month AED": p.cost_per_month_aed,
            "AED per 1,000 relevant impressions": cpm,
            "AED per 1,000 range": f"{cpm_lo:,.1f}–{cpm_hi:,.1f}",
            "Mean visibility": r.reach.mean_visibility,
            "Label": m["unique_month"].label,
        })
    df = pd.DataFrame(rows)
    st.dataframe(df.style.format({"Daily impressions (placement)": "{:,.0f}", "Daily impressions (advertiser)": "{:,.0f}",
                                  "Unique / month": "{:,.0f}", "Car-relevant / month": "{:,.0f}",
                                  "Cost / month AED": "{:,.0f}", "AED per 1,000 relevant impressions": "{:,.1f}",
                                  "Mean visibility": "{:.3f}"}),
                 hide_index=True, width="stretch")
    st.markdown(f"Costs are ASSUMPTIONS from config {badge('ASSUMPTION')}; reach numbers are "
                f"{badge(df['Label'].iloc[0])}. Cost per thousand uses advertiser impressions "
                f"(digital faces divided by share of voice) × interest share.", unsafe_allow_html=True)

    vals = [r.profile.relevant_reach for r in res.placements.values()]
    order = np.argsort([-v.value for v in vals])
    ids = [list(res.placements)[i] for i in order]
    vals = [vals[i] for i in order]
    fig = go.Figure(go.Bar(
        x=ids, y=[v.value for v in vals], marker_color=SERIES[0],
        error_y=dict(type="data", symmetric=False, array=[v.high - v.value for v in vals],
                     arrayminus=[v.value - v.low for v in vals], color="#bbbbbb"),
        text=[fmt_num(v.value) for v in vals], textposition="outside", cliponaxis=False))
    fig.update_layout(**PLOT_LAYOUT, height=360, title_text="Car-relevant unique people per month (base, low–high)",
                      yaxis_title="People / month")
    st.plotly_chart(fig, width="stretch")


def page_duplication(res: Results, budget: float) -> None:
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
    fig = go.Figure(go.Heatmap(z=off.values, x=ids, y=ids, text=text, texttemplate="%{text}",
                               colorscale="Blues", zmin=0, zmax=max(0.6, float(np.nanmax(off.values)) if len(ids) > 1 else 1),
                               colorbar=dict(title="share of smaller", tickformat=".0%"),
                               hovertemplate="%{y} × %{x}<br>%{text}<extra></extra>"))
    fig.update_layout(**PLOT_LAYOUT, height=420, title_text="Overlap in unique people per month (and % of the smaller audience)")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")
    label_line("Overlap uses shared road segments, or the corridor rule (tau) when larger.", "ASSUMPTION")
    rules = [{"pair": f"{a} × {b}", "rule": res.overlap_rules.loc[a, b], "overlap people": mat.loc[a, b]}
             for i, a in enumerate(ids) for b in ids[i + 1:]]
    st.dataframe(pd.DataFrame(rules).style.format({"overlap people": "{:,.0f}"}), hide_index=True,
                 width="stretch")

    st.subheader(f"Greedy plan within AED {budget:,.0f}")
    if not res.plan:
        st.info("No placement fits the budget.")
        return
    plan = pd.DataFrame([s.__dict__ for s in res.plan])
    st.dataframe(plan.rename(columns={
        "step": "Step", "placement": "Add", "cost_aed": "Cost AED", "incremental_relevant": "Incremental relevant reach",
        "relevant_per_1k_aed": "Relevant reach per 1,000 AED", "cumulative_cost_aed": "Spent AED",
        "combined_relevant": "Combined relevant reach", "naive_relevant": "Naive sum"}).style.format(
        {"Cost AED": "{:,.0f}", "Incremental relevant reach": "{:,.0f}", "Relevant reach per 1,000 AED": "{:,.0f}",
         "Spent AED": "{:,.0f}", "Combined relevant reach": "{:,.0f}", "Naive sum": "{:,.0f}"}),
        hide_index=True, width="stretch")
    last = res.plan[-1]
    lost = last.naive_relevant - last.combined_relevant
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[f"Step {s.step}: +{s.placement}" for s in res.plan], y=[s.naive_relevant for s in res.plan],
                         name="Naive sum", marker_color="#6b7280"))
    fig.add_trace(go.Bar(x=[f"Step {s.step}: +{s.placement}" for s in res.plan],
                         y=[s.combined_relevant for s in res.plan], name="Combined (de-duplicated)",
                         marker_color=SERIES[0]))
    fig.update_layout(**PLOT_LAYOUT, barmode="group", height=340, yaxis_title="Car-relevant people / month",
                      title_text=f"Duplication removes {fmt_num(lost)} people ({lost / last.naive_relevant:.0%}) from the naive sum",
                      legend=LEGEND_TOP)
    st.plotly_chart(fig, width="stretch")
    label_line(f"All four placements: {fmt_num(res.combined_unique_all)} combined unique people vs "
               f"{fmt_num(res.naive_unique)} naive sum.", "ESTIMATE")


def page_delivery(res: Results, pid: str) -> None:
    st.header("Planned vs actual delivery")
    label_line(res.delivery_label.split(": ", 1)[1], "SAMPLE")
    df = res.delivery
    summary = df.groupby("placement").agg(planned=("planned", "sum"), forecast=("forecast", "sum"),
                                          actual=("actual", "sum")).reset_index()
    summary["news effect"] = summary["forecast"] / summary["planned"] - 1
    summary["delivery index"] = summary["actual"] / summary["planned"]
    st.dataframe(summary.style.format({"planned": "{:,.0f}", "forecast": "{:,.0f}", "actual": "{:,.0f}",
                                       "news effect": "{:+.1%}", "delivery index": "{:.2f}"}),
                 hide_index=True, width="stretch")
    d = df[df["placement"] == pid]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["week_start"], y=d["planned"], name="Planned", marker_color="#6b7280"))
    fig.add_trace(go.Bar(x=d["week_start"], y=d["forecast"], name="News-adjusted forecast", marker_color="#F5A524"))
    fig.add_trace(go.Bar(x=d["week_start"], y=d["actual"], name="Actual (SAMPLE)", marker_color=SERIES[0]))
    fig.update_layout(**PLOT_LAYOUT, barmode="group", height=340, title_text=f"{pid}: weekly advertiser impressions",
                      yaxis_title="Impressions / week", xaxis_title="Week starting",
                      legend=LEGEND_TOP)
    st.plotly_chart(fig, width="stretch")
    fig = go.Figure()
    for i, (p, g) in enumerate(df.groupby("placement")):
        fig.add_trace(go.Scatter(x=g["week_start"], y=g["delivery_index"], name=p, mode="lines+markers",
                                 line=dict(color=SERIES[i % len(SERIES)], width=2)))
    fig.add_hline(y=1.0, line_dash="dot", line_color="#999999")
    fig.update_layout(**PLOT_LAYOUT, height=320, title_text="Delivery index (actual / planned) per week",
                      yaxis_tickformat=".0%", xaxis_title="Week starting", legend=LEGEND_TOP)
    st.plotly_chart(fig, width="stretch")
    st.caption("Plan = baseline advertiser impressions × days. News-adjusted forecast = plan with the switched-on "
               "events from Area signals (ESTIMATE). Actual = forecast × simulated traffic factor × (actual plays / "
               "planned plays) from the media owner's play log (SAMPLE).")


def page_sensitivity(pid: str, overrides: tuple, road_rows: tuple) -> None:
    st.header(f"Sensitivity: what moves {pid}'s unique monthly audience")
    df = get_sensitivity(pid, overrides, road_rows)
    base = df["base_unique"].iloc[0]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=df["parameter"], x=df["unique_at_low"] - base, base=base, orientation="h",
                         name="parameter at low", marker_color="#6b7280",
                         customdata=df[["low_value", "unique_at_low"]],
                         hovertemplate="%{y} = %{customdata[0]:.3g}<br>unique %{customdata[1]:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(y=df["parameter"], x=df["unique_at_high"] - base, base=base, orientation="h",
                         name="parameter at high", marker_color=SERIES[0],
                         customdata=df[["high_value", "unique_at_high"]],
                         hovertemplate="%{y} = %{customdata[0]:.3g}<br>unique %{customdata[1]:,.0f}<extra></extra>"))
    fig.add_vline(x=base, line_color="#dddddd", line_width=1)
    fig.update_layout(**PLOT_LAYOUT, barmode="overlay", height=460,
                      title_text=f"Unique people / month; base {fmt_num(base)}", xaxis_title="Unique people / month",
                      legend=LEGEND_TOP)
    st.plotly_chart(fig, width="stretch")
    top = df.iloc[-1]
    st.markdown(f"**{top['parameter']}** moves the result most: {fmt_num(top['unique_at_low'])} to "
                f"{fmt_num(top['unique_at_high'])} across its range. Ranges use the configured low / high, "
                f"else base ± 25 %.")
    st.dataframe(df.iloc[::-1].style.format({"low_value": "{:.3g}", "base_value": "{:.3g}", "high_value": "{:.3g}",
                                             "unique_at_low": "{:,.0f}", "unique_at_high": "{:,.0f}",
                                             "base_unique": "{:,.0f}", "swing": "{:,.0f}"}),
                 hide_index=True, width="stretch")


def page_activation(res: Results) -> None:
    st.header("Activation: re-engaging the exposed audience")
    label_line("Nothing is executed in the MVP. These files are what a data partner or platform needs.", "CONCEPT")
    c1, c2 = st.columns(2)
    c1.download_button("Download exposure zones (GeoJSON)", res.zones_geojson, "ooh_exposure_zones.geojson",
                       "application/geo+json", width="stretch")
    c2.download_button("Download centre + radius list (CSV)", res.radius_csv, "ooh_zones_radius.csv", "text/csv",
                       width="stretch")
    st.dataframe(pd.read_csv(io.StringIO(res.radius_csv)), hide_index=True, width="stretch")
    st.caption(f"Platform radius uses a {PLATFORM_MIN_RADIUS_KM:g} km minimum (ASSUMPTION; check each platform). "
               "A circle that large also reaches people who never passed the face.")
    st.subheader("Routes")
    st.dataframe(pd.DataFrame([
        ["Location data partner + DSP", "Partner (Blis, Azira) flags consented devices seen in the zone during the "
         "flight; the audience is pushed to DV360 or The Trade Desk", "High", "CONCEPT"],
        ["Platform radius targeting", "Meta, Google, Snap or TikTok target people in or near the zone", "Medium-low",
         "Files above"],
        ["Synced digital OOH", "Mobile ads run nearby while the digital face shows the creative", "Medium", "CONCEPT"],
    ], columns=["Route", "How it works", "Precision", "MVP"]), hide_index=True, width="stretch")
    st.subheader("Measuring it")
    st.markdown("Exposed group vs a matched control group that never passed the zone: showroom visits, site "
                "visits and test-drive bookings. Google Trends gives a free brand-search lift signal.")
    st.subheader("Restrictions")
    st.markdown(
        "- **Privacy:** UAE Federal Personal Data Protection Law (Decree-Law 45 of 2021). Consented, aggregated "
        "data only; never identify individuals; keep minimum audience thresholds.\n"
        "- **Apple ATT:** iPhone users can refuse tracking, so iOS audiences shrink.\n"
        "- **Platform limits:** minimum radius and audience sizes; policy bans on sensitive locations.\n"
        "- **Data partner terms:** audiences usually stay inside the partner's DSP or clean room.")


def page_signals(res: Results, pcfg, params: Params) -> None:
    st.header("Area signals: online news in the forecast")
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
            rows.append({"Face": pid, "Events applied": len({h["event"] for h in f.applied}),
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


def page_sources() -> None:
    st.header("Data sources")
    data = diagram_data()
    srcs = data["sources"]
    connected = [x for x in srcs if x["status"] != "not connected"]
    sample = [x for x in srcs if x["status"] == "sample"]
    live = [x for x in srcs if x["status"] in ("live", "cached")]
    ai = data["engine"]["ai"]
    st.markdown(
        f"<span class='ooh-live'></span>**{len(live)}** live or cached · **{len(connected)}** of {len(srcs)} "
        f"connected · **{len(sample)}** still placeholders · Claude: **{ai['status']}**. "
        "Geometry and traffic data do the counting. Claude explains the numbers and turns news into dated "
        "events; the reach model applies them with effect sizes from config.",
        unsafe_allow_html=True)
    components.html(brain_html(data), height=820, scrolling=False)

    st.subheader("Confidence by source")
    df = pd.DataFrame([{
        "Source": x["name"], "Status": x["status"], "Confidence": x["score"], "Potential": x["potential"],
        "Label of its numbers": x["label"], "Feeds": ", ".join(x["feeds_names"]),
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
    acfg, pcfg = load_assumptions(), load_placements()
    st.markdown(MOTION_CSS, unsafe_allow_html=True)
    page, pid, overrides, road_rows, use_llm = sidebar(acfg, pcfg)
    okey = tuple(sorted(overrides.items()))
    ekey = tuple(sorted(st.session_state.get("event_overrides", {}).items()))
    results = get_results(okey, road_rows, ekey, ledger_stamp())
    params = Params(build_cfg(road_rows), overrides)

    if page in ANALYST_PAGES:
        analyst_tag()
    if page == "Decision":
        page_decision(results, pcfg, params)
    elif page == "Billboard league":
        page_league(results)
    elif page == "Audience":
        page_audience(results)
    elif page == "Campaign health":
        page_health(results, pcfg, params)
    elif page == "Map":
        page_map(results, params, pid)
    elif page == "Data sources":
        page_sources()
    elif page == "Placement detail":
        page_detail(results, pid, params, use_llm, pcfg.campaign.brand)
    elif page == "Compare locations":
        page_compare(results)
    elif page == "Duplication and plan":
        page_duplication(results, pcfg.campaign.budget_aed)
    elif page == "Planned vs actual":
        page_delivery(results, pid)
    elif page == "Sensitivity":
        page_sensitivity(pid, okey, road_rows)
    elif page == "Activation":
        page_activation(results)
    elif page == "Area signals":
        page_signals(results, pcfg, params)
    else:
        page_assumptions(results, acfg, params)


main()
