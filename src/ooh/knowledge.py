"""The knowledge layer: every data source files facts here; each campaign reads only what it needs.

::

    data sources  ->  facts (campaign-free, one per number or statement, with source and trust)
                  ->  select(campaign, location): relevance score + one-line reason per fact
                  ->  outcomes (reach, campaign audience, value, fit, timing, forecast, profile)

* A fact names the registry sources it comes from (``sources.registry`` ids) and the outcomes it
  feeds, so the data-flow diagram is drawn from the facts themselves, not from a hand-kept list.
* Relevance rules and location-scoring weights live in ``config/knowledge.yaml``: readable rules,
  labelled ASSUMPTION, never a model.
* Nothing here recalculates reach. Facts are read off the pipeline results, the people-numbers
  store, the road-event ledger and the config files.
"""

from __future__ import annotations

import math

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import yaml

from .config import CONFIG_DIR, INPUT_DIR, Campaign, Params, PlacementConfig

KNOWLEDGE_PATH = CONFIG_DIR / "knowledge.yaml"


@lru_cache(maxsize=1)
def rules() -> dict:
    return yaml.safe_load(KNOWLEDGE_PATH.read_text())


# --------------------------------------------------------------------------- the fact


@dataclass
class Fact:
    id: str
    location: str                     # placement id, or "all" for Dubai-wide facts
    topic: str                        # key of rules()["topics"]
    title: str                        # what it is, in plain words
    display: str                      # the number as an executive reads it ("215k vehicles a day")
    sources: list[str]                # sources.registry ids
    trust: str                        # VERIFIED / ESTIMATE / ASSUMPTION / SAMPLE / CONCEPT
    feeds: list[str]                  # outcome ids it changes; [] = context only
    tags: list[str] = field(default_factory=list)
    value: float | None = None
    unit: str = ""
    core: bool = False                # a number every plan rests on
    weak: bool = False                # capacity, old figure or placeholder
    start: date | None = None         # dated facts (events)
    end: date | None = None
    detail: str = ""
    url: str = ""
    quote: str = ""

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["start"] = self.start.isoformat() if self.start else None
        d["end"] = self.end.isoformat() if self.end else None
        return d


def people(x: float) -> str:
    x = max(0.0, float(x))
    if x >= 1e6:
        return f"{x / 1e6:.1f}M"
    if x >= 1e4:
        return f"{x / 1e3:.0f}k"
    if x >= 1e3:
        return f"{x / 1e3:.1f}k"
    return f"{x:,.0f}"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


POI_TAGS = {
    "Car showrooms and services": ["cars", "drivers"],
    "Retail and malls": ["families", "luxury", "general"],
    "Hotels and tourism": ["luxury", "tourists"],
    "Offices and business": ["business", "premium"],
    "Food and leisure": ["families", "general"],
}
PREMIUM_AREAS = {"DIFC", "Downtown", "Dubai Marina"}  # same rule as the audience profile (ASSUMPTION)


# --------------------------------------------------------------------------- build


def _placement_facts(pid: str, r, params: Params, price_rank: int, n: int) -> list[Fact]:
    p, reach, prof, m = r.prep.placement, r.reach, r.profile, r.metrics
    base = reach.scenarios["base"]
    flows = base.flows
    out: list[Fact] = []

    def add(key: str, **kw) -> None:
        out.append(Fact(id=f"{pid}:{key}", location=pid, **kw))

    # ---- traffic
    if len(flows):
        main = flows.iloc[0]
        scored = r.scored
        sp_src = ""
        if len(scored) and "speed_source" in scored:
            inc = scored[scored["included"] & (scored["label"] == main["road"])]
            sp_src = str(inc["speed_source"].iloc[0]) if len(inc) else ""
        add("main_road", topic="traffic", title=f"Main road in view: {main['road']}",
            display=f"{int(main['lanes'])} lanes · {str(main['highway']).replace('_', ' ')}",
            value=float(main["lanes"]), unit="lanes", sources=["osm"], trust="VERIFIED",
            feeds=["reach"], tags=["drivers"],
            detail=f"Lane count from {main['lanes_source']}")
        add("vehicles", topic="traffic", title="Vehicles passing within view",
            display=f"{people(m['vehicles_day'].value)} vehicles a day", value=m["vehicles_day"].value,
            unit="vehicles/day", sources=["rta", "osm"], trust=m["vehicles_day"].label, feeds=["reach", "target"],
            tags=["drivers", "general"], core=True,
            detail="RTA lane capacity x utilisation (ASSUMPTION) over the visible road flows")
        add("people_day", topic="traffic", title="People passing a day",
            display=f"{people(m['people_day'].value)} people a day", value=m["people_day"].value, unit="people/day",
            sources=["rta", "assumptions"], trust=m["people_day"].label, feeds=["reach", "timing"],
            tags=["drivers", "general"], core=True, detail="Vehicles x occupancy (ASSUMPTION)")
        tomtom = "tomtom" in sp_src.lower()
        speed = float(main["speed_kmh"])
        add("speed", topic="visibility", title=f"Speed on {main['road']}", display=f"{speed:.0f} km/h",
            value=speed, unit="km/h", sources=["tomtom_flow"] if tomtom else ["osm"],
            trust="ESTIMATE" if tomtom else "VERIFIED", feeds=["reach"], tags=["drivers"],
            detail=("TomTom Traffic Flow, live reading" if tomtom else f"Speed limit / road class ({sp_src or 'OSM'})"))
        secs = float(main["visible_length_m"]) / (speed / 3.6) if speed else 0.0
        add("dwell", topic="visibility", title="Time the board is in view from the main road",
            display=f"≈ {secs:.0f} seconds per pass", value=secs, unit="seconds",
            sources=["osm", "tomtom_flow"] if tomtom else ["osm"], trust="ESTIMATE", feeds=["reach"],
            tags=["drivers", "general"], detail=f"{main['visible_length_m']:.0f} m of road in view at {speed:.0f} km/h")
        add("visibility", topic="visibility", title="How well drivers see it",
            display=f"{main['mean_V'] * 100:.0f} / 100 visibility on the main road", value=float(main["mean_V"]),
            unit="0-1", sources=["osm", "assumptions"], trust="ESTIMATE", feeds=["reach"], tags=["drivers"],
            detail="Distance, angle, obstruction (OSM buildings), size and dwell, combined")
    if reach.metro and m["metro_impressions_day"].value > 0:
        add("metro", topic="traffic", title=f"Metro riders at {reach.metro.station}",
            display=f"{people(reach.metro.daily_riders)} riders a day", value=reach.metro.daily_riders,
            unit="riders/day", sources=["metro"], trust=reach.metro.label, feeds=["reach"],
            tags=["commuters", "general"], weak=reach.metro.label == "SAMPLE", detail=reach.metro.source)

    # ---- audience
    u = m["unique_month"]
    add("unique", topic="audience", title="Different people passing a month",
        display=f"{people(u.value)} people a month", value=u.value, unit="people/month",
        sources=["rta", "assumptions"], trust=u.label, feeds=["reach", "target", "value"], tags=["general"],
        core=True, detail=f"Monthly views / pass frequency (ASSUMPTION); range {people(u.low)}–{people(u.high)}")
    road_share = base.road_impressions_day / base.impressions_day if base.impressions_day else 1.0
    add("road_share", topic="audience", title="Views from drivers (vs metro riders)",
        display=f"{road_share:.0%} drivers", value=road_share, unit="share",
        sources=["rta", "metro"] if reach.metro else ["rta"], trust="ESTIMATE", feeds=["fit", "profile"],
        tags=["drivers"])
    add("rush", topic="audience", title="Traffic in the two rush hours (7-10 am, 5-8 pm)",
        display=f"{prof.commuter_share:.0%} of the day", value=prof.commuter_share, unit="share",
        sources=["assumptions"], trust="ASSUMPTION", feeds=["fit", "profile"], tags=["commuters", "drivers"],
        detail="Standard Dubai commuter curve")
    meta, label = prof.meta, ("SAMPLE" if prof.meta_is_sample else "ESTIMATE")
    age = meta.get("age", {})
    if age:
        core_age = sum(v for k, v in age.items() if k in ("25-34", "35-44", "45-54"))
        add("age", topic="audience", title="Aged 25-54", display=f"{core_age:.0%} of people around the board",
            value=core_age, unit="share", sources=["meta"], trust=label, feeds=["profile"],
            tags=["general", "premium"], weak=prof.meta_is_sample)
    if meta.get("gender"):
        add("gender", topic="audience", title="Men among people around the board",
            display=f"{meta['gender'].get('male', 0):.0%} men", value=meta["gender"].get("male", 0), unit="share",
            sources=["meta"], trust=label, feeds=["profile"], tags=["general"], weak=prof.meta_is_sample)
    for key, share in (meta.get("interest_share") or {}).items():
        add(f"interest_{key}", topic="audience", title=f"Interested in {key.replace('_', ' ')} (Meta)",
            display=f"{share:.0%} of people around the board", value=share, unit="share", sources=["meta"],
            trust=label, feeds=[] if prof.meta_is_sample else ["target"], tags=[f"interest:{key}"],
            weak=prof.meta_is_sample,
            detail="Placeholder: the campaign's assumed share is used instead" if prof.meta_is_sample
            else "Used as the campaign audience share")
    premium = p.area.split("/")[0].strip() in PREMIUM_AREAS
    add("premium", topic="audience", title="Income signal",
        display="Premium area" if premium else "Mixed-income area", value=1.0 if premium else 0.0, unit="flag",
        sources=["assumptions"], trust="ASSUMPTION", feeds=["fit", "profile"],
        tags=["premium", "luxury"] if premium else ["general"])

    # ---- places nearby (OSM points of interest within 1 km)
    for cat, n_poi in prof.poi_counts.items():
        add(f"poi_{_slug(cat)}", topic="places", title=f"{cat} within 1 km", display=f"{n_poi}",
            value=float(n_poi), unit="places", sources=["osm"], trust="VERIFIED", feeds=["fit", "profile"],
            tags=POI_TAGS.get(cat, ["general"]))

    # ---- format & price (billboard inventory)
    sov = p.share_of_voice
    add("format", topic="media", title="Format",
        display=(f"Digital screen · our ad 1 in {round(1 / sov)}" if p.type == "digital" and sov < 1
                 else f"{p.type.title()} · our ad always on show"), value=sov, unit="share of voice",
        sources=["inventory"], trust="VERIFIED", feeds=["forecast"], tags=["general"])
    add("size", topic="media", title="Face size", display=f"{p.width_m:g} × {p.height_m:g} m",
        value=p.face_area_m2, unit="m²", sources=["inventory"], trust="VERIFIED", feeds=["reach"])
    ordinal = {2: "2nd", 3: "3rd"}.get(price_rank, f"{price_rank}th")
    word = "cheapest" if price_rank == 1 else "most expensive" if price_rank == n else f"{ordinal} cheapest"
    add("price", topic="media", title="Price level", display=f"{word} of our {n} boards",
        value=float(p.cost_per_month_aed), unit="AED/month", sources=["inventory"], trust="ASSUMPTION",
        feeds=["value"], core=True, detail="Planning price until media-owner quotes arrive")
    return out


def _brief_facts(pcfg: PlacementConfig, params: Params) -> list[Fact]:
    out = []
    for c in pcfg.campaign_options():
        share = c.interest_share if c.interest_share is not None else params.base("interest_share")
        tag = [f"campaign:{c.id}", "cars"]
        out.append(Fact(f"brief:{c.id}:audience", "all", "audience", f"{c.title}: who we are after",
                        f"{c.audience_short}: {share:.0%} of passers-by" if share < 1 else f"{c.audience_short}: everyone",
                        ["briefs"], "ASSUMPTION", ["target"], tag, share, "share", core=True,
                        detail=c.audience))
        out.append(Fact(f"brief:{c.id}:window", "all", "media", f"{c.title}: when and how much",
                        f"{c.plan_start:%d %b} – {c.plan_end:%d %b %Y}", ["briefs"], "VERIFIED",
                        ["value", "timing", "forecast"], tag, c.budget_aed, "AED", core=True,
                        start=c.plan_start, end=c.plan_end, detail="Budget sets how many boards the plan can buy"))
    return out


def _dsc_fact() -> list[Fact]:
    path = INPUT_DIR / "dsc_population.json"
    if not path.exists():
        return []
    d = yaml.safe_load(path.read_text())
    sample = bool(d.get("is_sample"))
    return [Fact("all:dsc", "all", "audience", "Dubai population (sanity check on the Meta mix)",
                 f"{people(d.get('emirate_total', 0))} residents · {d.get('gender', {}).get('male', 0):.0%} men",
                 ["dsc"], "SAMPLE" if sample else "VERIFIED", [], ["general"], float(d.get("emirate_total", 0)),
                 "people", weak=sample, detail="Shown for context; no number is calculated from it")]


def _people_facts(pcfg: PlacementConfig) -> list[Fact]:
    from . import footprint as fp

    topic_of = {"event_attendance": "crowds", "venue_footfall": "places", "new_homes_or_offices": "growth",
                "transit_ridership": "traffic", "traffic_count": "traffic"}
    per = {"year": " a year", "month": " a month", "week": " a week", "day": " a day", "hour": " an hour"}
    out = []
    this_year = date.today().year
    for g in fp.merge_by_name(fp.group_facts(fp.all_facts(pcfg))):
        dated = g.event_start is not None and g.kind in ("event_attendance", "transit_ridership")
        old = bool(g.figure_year and g.figure_year < this_year - 2)
        for loc in g.placements or ["all"]:
            when = f" · {g.event_start:%d %b %Y}" if g.event_start else (f" · {g.figure_year} figure" if g.figure_year else "")
            out.append(Fact(
                f"{loc}:people:{_slug(g.key)}", loc, topic_of.get(g.kind, "crowds"), g.what,
                f"{people(g.value)} {g.unit}{per.get(g.period, '')}{when}", ["people_news"], "ESTIMATE",
                ["timing"] if dated and g.measure != "capacity" else [], list(g.tags), g.value, g.unit,
                weak=g.measure == "capacity" or old, start=g.event_start if dated else None,
                end=(g.event_end or g.event_start) if dated else None, detail=g.note,
                url=g.sources[0]["url"] if g.sources else "", quote=g.sources[0]["quote"] if g.sources else ""))
    return out


def _road_event_facts(res, pcfg: PlacementConfig, params: Params) -> list[Fact]:
    from . import signals

    types = params.cfg.event_types
    names = {"full_closure": "Road closed", "partial_closure": "Lanes closed", "roadworks": "Roadworks",
             "major_event": "Major event"}
    out = []
    for ev in res.events:
        if ev.get("type") not in types:
            continue
        hit = [p.id for p in pcfg.placements if signals.affects(ev, p, types)]
        for loc in hit:
            out.append(Fact(f"{loc}:road:{ev['id']}", loc, "road_events",
                            f"{names.get(ev['type'], ev['type'])}: {ev.get('note') or ev.get('corridor') or ''}".strip(": "),
                            f"{date.fromisoformat(ev['date']):%d %b}" + (
                                f" – {date.fromisoformat(ev['end_date']):%d %b}" if ev.get("end_date") != ev["date"] else ""),
                            ["news"], "ESTIMATE", ["forecast"] if ev.get("enabled") else [], ["drivers"],
                            start=date.fromisoformat(ev["date"]), end=date.fromisoformat(ev["end_date"]),
                            detail=("Switched on in the forecast" if ev.get("enabled") else "Switched off")))
    return out


def _delivery_facts(res) -> list[Fact]:
    out = []
    d = res.delivery
    if d is None or d.empty:
        return out
    for pid, g in d.groupby("placement"):
        logged = g[~g["play_log"].str.startswith(("n/a", "no play"))]
        if logged.empty:
            continue
        ratio = float(logged["play_factor"].mean())
        label = "SAMPLE" if (logged["play_log"] == "SAMPLE").any() else "VERIFIED"
        out.append(Fact(f"{pid}:plays", pid, "delivery", "Digital plays delivered vs booked",
                        f"{ratio:.0%} of booked plays", ["playlog"], label, ["forecast"], ["general"], ratio, "share",
                        weak=label == "SAMPLE"))
    return out


def build(res, pcfg: PlacementConfig, params: Params) -> list[Fact]:
    """Every fact the app knows, campaign-free. Fast: reads results and files only."""
    costs = sorted(r.prep.placement.cost_per_month_aed for r in res.placements.values())
    facts: list[Fact] = []
    for pid, r in res.placements.items():
        rank = costs.index(r.prep.placement.cost_per_month_aed) + 1
        facts += _placement_facts(pid, r, params, rank, len(costs))
    facts += _brief_facts(pcfg, params) + _dsc_fact() + _people_facts(pcfg)
    facts += _road_event_facts(res, pcfg, params) + _delivery_facts(res)
    return facts


# --------------------------------------------------------------------------- select


@dataclass
class Picked:
    fact: Fact
    score: float
    reason: str
    used: bool


def campaign_tags(campaign: Campaign) -> set[str]:
    tags = rules()["campaign_tags"]
    return set(tags.get(campaign.id, tags["default"])) | set(campaign.news_tags)


def relevance(f: Fact, campaign: Campaign) -> tuple[float, str]:
    R = rules()["relevance"]
    for t in f.tags:
        if t.startswith("campaign:"):
            return (1.0, "this campaign's brief") if t == f"campaign:{campaign.id}" else (0.0, "another campaign's brief")
        if t.startswith("interest:"):
            key = t.split(":", 1)[1]
            if campaign.meta_interest != key:
                return 0.0, "interest of a different audience"
            score = rules()["topics"][f.topic]["base"] + R["tag_match"] - (R["weak"] if f.weak else 0)
            return min(1.0, score), "the campaign's own interest" + (" (placeholder)" if f.weak else "")
    if f.core:
        return 1.0, "core number every plan rests on"
    score = rules()["topics"][f.topic]["base"]
    reasons = []
    hit = set(f.tags) & campaign_tags(campaign)
    if hit:
        score += R["tag_match"]
        reasons.append(f"{campaign.title} audience: {', '.join(sorted(hit))}")
    if f.start is not None:
        end = f.end or f.start
        if end >= campaign.plan_start and f.start <= campaign.plan_end:
            score += R["in_window"]
            reasons.insert(0, "inside the campaign window")
        else:
            score *= R["out_window"]
            reasons.insert(0, "outside the campaign window")
    if f.weak:
        score -= R["weak"]
        reasons.append("weak figure (capacity, old or placeholder)")
    if not reasons:
        reasons.append("general background")
    return max(0.0, min(1.0, score)), "; ".join(reasons[:2])


def select(facts: list[Fact], campaign: Campaign, location: str | None = None) -> list[Picked]:
    """Facts for one campaign (and optionally one location), most relevant first."""
    thr = rules()["relevance"]["threshold"]
    out = []
    for f in facts:
        if location and f.location != location and not (f.location == "all" and "people_news" not in f.sources):
            continue  # Dubai-wide crowds belong to "elsewhere in Dubai", not to this board
        s, why = relevance(f, campaign)
        out.append(Picked(f, s, why, s >= thr))
    return sorted(out, key=lambda p: (-p.score, p.fact.topic, p.fact.title))


# --------------------------------------------------------------------------- score locations


def score_locations(res, pcfg: PlacementConfig, campaign: Campaign, facts: list[Fact],
                    pulse: dict | None = None) -> dict:
    """0-100 per criterion per location, relative to the best location, with a 'why' for each."""
    R = rules()
    pids = list(res.placements)
    rel = {pid: r.profile.relevant_reach.value for pid, r in res.placements.items()}
    cost = {pid: r.prep.placement.cost_per_month_aed for pid, r in res.placements.items()}
    label = {pid: r.prep.placement.label for pid, r in res.placements.items()}

    def scaled(raw: dict) -> dict:
        top = max(raw.values()) if raw else 0
        return {k: (100 * v / top if top > 0 else 0.0) for k, v in raw.items()}

    by_fact = {f.id: f for f in facts}
    crit: dict[str, dict] = {}

    t = scaled(rel)
    crit["target"] = {pid: {"score": t[pid], "why": f"{people(rel[pid])} {campaign.audience_short} a month"} for pid in pids}

    per = {pid: rel[pid] / cost[pid] if cost[pid] else 0 for pid in pids}
    v = scaled(per)
    best_v = max(per, key=per.get)
    crit["value"] = {pid: {"score": v[pid], "why": ("best audience for the price" if pid == best_v else
                                                   f"{per[best_v] / per[pid]:.1f}× less audience per unit of price than "
                                                   f"{label[best_v]}" if per[pid] else "no audience")} for pid in pids}

    signals = R["fit_signals"].get(campaign.id, R["fit_signals"]["default"])
    raw_sig: dict[str, dict] = {}
    for key in signals:
        vals = {}
        for pid in pids:
            if key.startswith("poi:"):
                f = by_fact.get(f"{pid}:poi_{_slug(key[4:])}")
            else:
                f = by_fact.get(f"{pid}:{ {'premium': 'premium', 'road_share': 'road_share', 'commuters': 'rush'}[key] }")
            vals[pid] = float(f.value) if f and f.value is not None else 0.0
        raw_sig[key] = vals
    fit_raw = {pid: 0.0 for pid in pids}
    wsum = sum(signals.values()) or 1.0
    for key, w in signals.items():
        top = max(raw_sig[key].values())
        for pid in pids:
            fit_raw[pid] += w * (raw_sig[key][pid] / top if top > 0 else 0.0) / wsum
    names = {"premium": "premium area", "road_share": "drivers", "commuters": "rush-hour traffic"}

    def fit_why(pid: str) -> str:
        parts = []
        for key in sorted(signals, key=lambda k: -signals[k]):
            val = raw_sig[key][pid]
            if key.startswith("poi:"):
                parts.append(f"{val:.0f} {key[4:].lower()}")
            elif key == "premium":
                parts.append("premium area" if val else "not a premium area")
            else:
                parts.append(f"{val:.0%} {names[key]}")
        return ", ".join(parts[:3])
    crit["fit"] = {pid: {"score": 100 * fit_raw[pid], "why": fit_why(pid)} for pid in pids}

    timing_raw = {pid: (pulse[pid].extra_target if pulse and pid in pulse else 0.0) for pid in pids}
    full = R.get("timing_full_share", 0.05)
    tm = {pid: min(100.0, 100 * timing_raw[pid] / (rel[pid] * full)) if rel[pid] else 0.0 for pid in pids}
    crit["timing"] = {pid: {"score": tm[pid], "why": (f"+{people(timing_raw[pid])} {campaign.audience_short} from "
                                                     f"{len(pulse[pid].events)} sourced crowd event(s), "
                                                     f"{timing_raw[pid] / rel[pid]:.1%} on top of the month"
                                                     if timing_raw[pid] else "no sourced crowd event in the window")}
                      for pid in pids}

    tw = R["trust_weight"]
    conf = {}
    for pid in pids:
        used = [p for p in select(facts, campaign, pid) if p.used and p.fact.location == pid]
        ws = [tw.get(p.fact.trust, 0.5) for p in used]
        weak = sum(1 for p in used if p.fact.trust in ("SAMPLE", "ASSUMPTION"))
        conf[pid] = {"score": 100 * sum(ws) / len(ws) if ws else 0.0,
                     "why": f"{len(used) - weak} of {len(used)} facts verified or estimated"}
    crit["confidence"] = conf

    for per in crit.values():          # one rounding, shared by every page (the browser re-weights these)
        for v in per.values():
            v["score"] = round(v["score"], 1)
    weights = dict(R["weights"].get(campaign.id, R["weights"]["default"]))
    total = {pid: sum(weights[k] * crit[k][pid]["score"] for k in weights) / (sum(weights.values()) or 1)
             for pid in pids}
    same = [k for k in crit
            if max(crit[k][p]["score"] for p in pids) - min(crit[k][p]["score"] for p in pids) < 8]
    return {"criteria": crit, "weights": weights, "total": total, "flat": same}


# --------------------------------------------------------------------------- the flow graph


def score_int(x: float) -> int:
    """Round half up, as the browser's Math.round does, so a score reads the same on every page."""
    return int(math.floor(x + 0.5))


def flow_graph(facts: list[Fact], campaign: Campaign, registry: list) -> dict:
    """Sources -> topics -> outcomes, counted from the facts; 'used' = relevant to this campaign."""
    R = rules()
    picks = select(facts, campaign)
    used_ids = {p.fact.id for p in picks if p.used}
    s2t: dict[tuple, list[int]] = {}
    t2o: dict[tuple, list[int]] = {}
    topic_n: dict[str, list[int]] = {}
    src_n: dict[str, list[int]] = {}
    src_feeds: dict[str, set] = {}
    for f in facts:
        for s in f.sources:
            src_feeds.setdefault(s, set()).update(f.feeds)
        u = f.id in used_ids
        topic_n.setdefault(f.topic, [0, 0])
        topic_n[f.topic][0] += 1
        topic_n[f.topic][1] += u
        for s in f.sources:
            src_n.setdefault(s, [0, 0])
            src_n[s][0] += 1
            src_n[s][1] += u
            s2t.setdefault((s, f.topic), [0, 0])
            s2t[(s, f.topic)][0] += 1
            s2t[(s, f.topic)][1] += u
        for o in f.feeds:
            t2o.setdefault((f.topic, o), [0, 0])
            t2o[(f.topic, o)][0] += 1
            t2o[(f.topic, o)][1] += u
    example = {}
    for p in picks:
        for s in p.fact.sources:
            example.setdefault(s, f"{p.fact.title}: {p.fact.display}")
    srcs = []
    for s in registry:
        n, u = src_n.get(s.id, [0, 0])
        srcs.append({"id": s.id, "name": s.name, "provider": s.provider, "status": s.status, "label": s.label,
                     "score": s.score, "phase": s.phase, "what": s.what, "facts": n, "used": u,
                     "example": example.get(s.id, ""),
                     "feeds": [o for o in R["outcomes"] if o in src_feeds.get(s.id, set())],
                     "context_only": n > 0 and not src_feeds.get(s.id),
                     "topics": sorted({t for (ss, t) in s2t if ss == s.id})})
    return {
        "campaign": {"id": campaign.id, "title": campaign.title, "emoji": campaign.emoji,
                     "audience_short": campaign.audience_short},
        "sources": srcs,
        "topics": [{"id": k, **v, "facts": topic_n.get(k, [0, 0])[0], "used": topic_n.get(k, [0, 0])[1]}
                   for k, v in R["topics"].items()],
        "outcomes": [{"id": k, **v} for k, v in R["outcomes"].items()],
        "s2t": [{"s": s, "t": t, "n": n, "used": u} for (s, t), (n, u) in s2t.items()],
        "t2o": [{"t": t, "o": o, "n": n, "used": u} for (t, o), (n, u) in t2o.items()],
        "total": len(facts), "used": len(used_ids),
    }
