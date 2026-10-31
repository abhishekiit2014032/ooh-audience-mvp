"""OOH Audience Intelligence: Streamlit dashboard for placements H1 to H4.

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import io
import sys
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

from ooh import narrative as narrative_mod  # noqa: E402
from ooh import news as news_mod  # noqa: E402
from ooh import sources as sources_mod  # noqa: E402
from ooh.brain_viz import brain_html, diagram_data  # noqa: E402
from ooh.activation import PLATFORM_MIN_RADIUS_KM  # noqa: E402
from ooh.config import (AssumptionConfig, Params, RoadClass, env_key, load_assumptions,  # noqa: E402
                        load_placements)
from ooh.geometry import cone_polygon_lonlat  # noqa: E402
from ooh.metrics import Metric, fmt_num  # noqa: E402
from ooh.pipeline import Results, compute, prepare, sensitivity  # noqa: E402

st.set_page_config(page_title="OOH Audience Intelligence", layout="wide")

PAGES = [
    "Map",
    "Data sources",
    "Placement detail",
    "Compare locations",
    "Duplication and plan",
    "Planned vs actual",
    "Sensitivity",
    "Activation",
    "Area news",
    "Assumptions and sources",
]
MAIN_SLIDERS = ["utilisation", "occupancy", "monthly_frequency", "cone_radius_m", "half_angle_deg",
                "interest_share", "obstruction_factor"]
BADGE_COLORS = {
    "VERIFIED": ("#0f5132", "#d1e7dd"),
    "ESTIMATE": ("#084298", "#cfe2ff"),
    "ASSUMPTION": ("#664d03", "#fff3cd"),
    "SAMPLE": ("#842029", "#f8d7da"),
    "CONCEPT": ("#41464b", "#e2e3e5"),
}
PLOT_LAYOUT = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                   margin=dict(l=10, r=10, t=70, b=10), font=dict(size=13),
                   title=dict(x=0, xanchor="left", y=0.98, yanchor="top"))
LEGEND_TOP = dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right")
SERIES = ["#4C9AFF", "#F5A524", "#36B37E", "#E5484D"]
SIGNAL_COLORS = {"traffic_risk": "#E5484D", "audience_boost": "#36B37E", "category": "#4C9AFF", "other": "#6b7280"}
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


@st.cache_resource(max_entries=24, show_spinner="Recomputing...")
def get_results(overrides: tuple, road_rows: tuple) -> Results:
    pcfg = load_placements()
    params = Params(build_cfg(road_rows), dict(overrides))
    return compute(get_preps(), pcfg, params)


@st.cache_resource(max_entries=24, show_spinner="Running sensitivity...")
def get_sensitivity(pid: str, overrides: tuple, road_rows: tuple) -> pd.DataFrame:
    params = Params(build_cfg(road_rows), dict(overrides))
    return sensitivity(get_preps()[pid], params)


@st.cache_data(ttl=3 * 3600, show_spinner="Fetching the latest news for this area (cached for the day)...")
def get_news(pid: str, use_llm: bool) -> dict:
    pcfg = load_placements()
    placement = next(p for p in pcfg.placements if p.id == pid)
    return news_mod.area_news(placement, pcfg.campaign.brand, use_llm=use_llm).to_dict()


def news_cached_today(pid: str) -> bool:
    from datetime import date

    from ooh.config import CACHE_DIR
    return (CACHE_DIR / "api" / "news" / f"{pid}_{date.today().isoformat()}.json").exists()


def signal_chip(signal: str) -> str:
    color = SIGNAL_COLORS.get(signal, "#6b7280")
    return (f"<span style='border:1px solid {color};color:{color};border-radius:10px;padding:0 7px;"
            f"font-size:0.72rem;white-space:nowrap'>{news_mod.SIGNALS.get(signal, signal)}</span>")


def news_list(items: list[dict], limit: int | None = None) -> None:
    for it in items[:limit]:
        reason = f" · <span style='opacity:0.6'>{it['reason']}</span>" if it.get("reason") else ""
        st.markdown(f"{signal_chip(it['signal'])} [{it['title']}]({it['url']}) "
                    f"<span style='opacity:0.6;font-size:0.8rem'>{it['source']} · {it['published']}</span>{reason}",
                    unsafe_allow_html=True)


MOTION_CSS = """
<style>
@keyframes oohFadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes oohPulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(54,179,126,.55); } 70% { box-shadow: 0 0 0 7px rgba(54,179,126,0); } }
[data-testid="stMain"] [data-testid="stElementContainer"],
[data-testid="stMain"] [data-testid="stExpander"] { animation: oohFadeUp .28s ease-out both; }
.ooh-card { transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
.ooh-card:hover { transform: translateY(-3px); box-shadow: 0 10px 24px rgba(0,0,0,.35); border-color: #4C9AFF !important; }
.ooh-live { display:inline-block; width:8px; height:8px; border-radius:50%; background:#36B37E; margin-right:6px;
            animation: oohPulse 1.8s infinite; vertical-align: middle; }
[data-testid="stSidebar"] label { transition: color .15s ease, transform .15s ease; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { color: #4C9AFF; transform: translateX(3px); }
[data-testid="stPlotlyChart"], [data-testid="stDeckGlJsonChart"] { border-radius: 10px; overflow: hidden; }
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
     font-family:'Source Sans Pro','Source Sans 3',-apple-system,sans-serif;color:#e6e9ef"></div>
<script>
const D = {data}; const root = document.getElementById('k');
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
function fmt(x) {{ const a = Math.abs(x); if (a >= 1e6) return (x/1e6).toFixed(2) + 'M';
  if (a >= 1e4) return (x/1e3).toFixed(1) + 'k'; return Math.round(x).toLocaleString(); }}
D.forEach((d, i) => {{
  const c = document.createElement('div');
  c.style.cssText = 'background:linear-gradient(160deg,#182033,#11161f);border:1px solid #2a3242;border-radius:12px;' +
    'padding:12px 14px;transition:transform .18s,border-color .18s;opacity:0;transform:translateY(6px)';
  c.onmouseenter = () => {{ c.style.transform = 'translateY(-3px)'; c.style.borderColor = '#4C9AFF'; }};
  c.onmouseleave = () => {{ c.style.transform = 'none'; c.style.borderColor = '#2a3242'; }};
  c.innerHTML = `<div style="font-size:12.5px;color:#8b93a7">${{d.t}}
     <span style="background:${{d.c[1]}};color:${{d.c[0]}};border-radius:4px;padding:0 5px;font-size:10px;font-weight:700;margin-left:4px">${{d.l}}</span></div>
     <div style="font-size:30px;font-weight:700;line-height:1.25"><span class="n">0</span>
     <span style="font-size:13px;font-weight:400;color:#8b93a7">${{d.u}}</span></div>`;
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
    """Dark blue (low visibility) to yellow (high)."""
    t = 0.0 if vmax <= 0 else min(1.0, v / vmax)
    stops = [(0.0, (49, 54, 149)), (0.35, (69, 117, 180)), (0.65, (116, 196, 118)), (1.0, (254, 224, 76))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return [int(c0[i] + k * (c1[i] - c0[i])) for i in range(3)] + [230]
    return [254, 224, 76, 230]


def lonlat_path(geom) -> list[list[float]]:
    xs, ys = geom.xy
    lon, lat = _to_wgs.transform(np.asarray(xs), np.asarray(ys))
    return [[float(a), float(b)] for a, b in zip(lon, lat)]


# --------------------------------------------------------------------------- sidebar


def sidebar(acfg: AssumptionConfig, pcfg) -> tuple[str, str, dict, tuple, bool]:
    st.sidebar.title("OOH Audience Intelligence")
    page = st.sidebar.radio("Page", PAGES, key="page")
    pid = st.sidebar.selectbox("Placement", [p.id for p in pcfg.placements],
                               format_func=lambda i: f"{i} · {next(p.name for p in pcfg.placements if p.id == i)}",
                               key="pid")

    if st.sidebar.button("Reset all assumptions", width="stretch"):
        for key in list(st.session_state.keys()):
            if key.startswith("param_") or key == "road_editor":
                del st.session_state[key]
        st.rerun()

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

    st.sidebar.subheader("Key assumptions")
    for key in MAIN_SLIDERS:
        control(key, st.sidebar)

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

    has_claude = env_key("ANTHROPIC_API_KEY") is not None
    use_llm = st.sidebar.toggle("Claude narratives", value=False, disabled=not has_claude,
                                help="Needs ANTHROPIC_API_KEY. Off by default: each new set of numbers is one "
                                     "API call (cached on disk). Without it a template writes the narrative.")
    keys = {k: env_key(k) is not None for k in ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "MAPILLARY_TOKEN",
                                               "ANTHROPIC_API_KEY"]}
    st.sidebar.caption("API keys: " + ", ".join(f"{k.split('_')[0].title()} {'set' if v else 'not set'}"
                                                for k, v in keys.items()))
    return page, pid, overrides, road_rows, use_llm


# --------------------------------------------------------------------------- pages


def page_map(res: Results, params: Params) -> None:
    st.header("Placements, exposure cones and visible road segments")
    view_mode = st.radio("View", ["All placements", "Selected placement (sidebar)"], horizontal=True,
                         key="map_view", label_visibility="collapsed")
    st.caption("Segments are coloured by visibility score V (blue = low, yellow = high). Hover for the "
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
        pdk.Layer("PolygonLayer", cone_rows, get_polygon="polygon", get_fill_color=[255, 255, 255, 28],
                  get_line_color=[255, 255, 255, 140], line_width_min_pixels=1, pickable=True),
        pdk.Layer("PathLayer", seg_rows, get_path="path", get_color="color", width_min_pixels=4,
                  pickable=True),
        pdk.Layer("PathLayer", metro_rows, get_path="path", get_color=[229, 72, 77, 220], width_min_pixels=3,
                  pickable=True),
        pdk.Layer("ScatterplotLayer", pin_rows, get_position="position", get_radius=40,
                  get_fill_color=[229, 72, 77, 255], get_line_color=[255, 255, 255], line_width_min_pixels=2,
                  stroked=True, radius_min_pixels=6, pickable=True),
        pdk.Layer("TextLayer", pin_rows, get_position="position", get_text="label", get_size=15,
                  get_color=[255, 255, 255], get_pixel_offset=[0, -18]),
    ]
    if view_mode == "All placements":
        lats = [r.prep.snapped.lat for r in res.placements.values()]
        lons = [r.prep.snapped.lon for r in res.placements.values()]
        view = pdk.ViewState(latitude=float(np.mean(lats)), longitude=float(np.mean(lons)), zoom=11.0, pitch=0)
    else:
        focus = res.placements[st.session_state.get("pid", "H1")].prep.snapped
        view = pdk.ViewState(latitude=focus.lat, longitude=focus.lon, zoom=14.6, pitch=0)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="dark",
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
         f"Delivery index {res.delivery[res.delivery['placement'] == pid]['delivery_index'].mean():.2f} "
         f"over {res.delivery['week'].max()} weeks; see Planned vs actual", "SAMPLE"],
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

    st.subheader("What's happening nearby")
    if news_cached_today(pid) or st.button("Load the latest area news", key=f"news_btn_{pid}"):
        n = get_news(pid, use_llm)
        risk = [i for i in n["items"] if i["signal"] == "traffic_risk"]
        st.markdown(f"{n['summary']} {badge('ESTIMATE')}", unsafe_allow_html=True)
        if risk:
            st.warning(f"{len(risk)} traffic-risk headline(s) in the last 30 days: check delivery against plan.")
        news_list(sorted(n["items"], key=lambda i: i["signal"] == "other")[:5])
        st.caption(f"Headlines: Google News / GDELT, last 30 days (VERIFIED as published). "
                   f"Classification and summary: {n['summary_source']} (ESTIMATE). Full list on the Area news page.")
    else:
        st.caption("Fetches Google News and GDELT headlines for this area (about 30 s the first time each day).")

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
    summary = df.groupby("placement").agg(planned=("planned", "sum"), actual=("actual", "sum")).reset_index()
    summary["delivery index"] = summary["actual"] / summary["planned"]
    st.dataframe(summary.style.format({"planned": "{:,.0f}", "actual": "{:,.0f}", "delivery index": "{:.2f}"}),
                 hide_index=True, width="stretch")
    d = df[df["placement"] == pid]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["week_start"], y=d["planned"], name="Planned", marker_color="#6b7280"))
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
    st.caption("Plan = baseline advertiser impressions × days. Actual = plan × campaign traffic factor × "
               "(actual plays / planned plays) from the media owner's play log (digital faces only).")


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


def page_news(pid: str, use_llm: bool, pcfg) -> None:
    placement = next(p for p in pcfg.placements if p.id == pid)
    st.header(f"Area news: {placement.id} · {placement.area}")
    st.markdown("Latest headlines about the corridor and the area around the face, sorted into signals a planner "
                "can act on. Context only: news never changes the reach numbers. " + badge("VERIFIED") +
                " headlines as published · " + badge("ESTIMATE") + " classification", unsafe_allow_html=True)
    n = get_news(pid, use_llm)
    if not n["items"]:
        st.info("No headlines found, or the news feeds were unreachable.")
    counts = n["counts"]
    cols = st.columns(4)
    for col, (key, label) in zip(cols, news_mod.SIGNALS.items()):
        col.markdown(f"<div style='border-left:3px solid {SIGNAL_COLORS[key]};padding-left:10px'>"
                     f"<div style='font-size:0.8rem;opacity:0.75'>{label}</div>"
                     f"<div style='font-size:1.6rem;font-weight:650'>{counts.get(key, 0)}</div></div>",
                     unsafe_allow_html=True)
    st.subheader("Summary")
    st.markdown(n["summary"])
    st.caption(f"{n['summary_source']}. Fetched {n['fetched_on']}; cached for the day.")
    signal = st.segmented_control("Show", ["All"] + list(news_mod.SIGNALS.values()), default="All", key="news_filter")
    items = n["items"] if signal in (None, "All") else [
        i for i in n["items"] if news_mod.SIGNALS[i["signal"]] == signal]
    st.subheader(f"Headlines ({len(items)})")
    news_list(items)
    if n["errors"]:
        with st.expander("Feed errors"):
            for e in n["errors"]:
                st.caption(e)
    st.caption("Sources: Google News RSS search (region AE) and the GDELT DOC 2.0 API, last 30 days. Suitable for "
               "a demo; a commercial product needs a licensed news API. Without ANTHROPIC_API_KEY, keyword rules "
               "classify the headlines.")


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
        "Geometry and traffic data do the counting; Claude only explains the numbers and sorts news.",
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
    results = get_results(okey, road_rows)
    params = Params(build_cfg(road_rows), overrides)

    if page == "Map":
        page_map(results, params)
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
    elif page == "Area news":
        page_news(pid, use_llm, pcfg)
    else:
        page_assumptions(results, acfg, params)


main()
