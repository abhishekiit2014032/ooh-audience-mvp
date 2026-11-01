"""People facts from the news: sourced numbers about how many people are at each location.

News is used as a data source for people footprints, not only for road closures:

* event_attendance   - visitors to a dated event (exhibition, concert, race, motor show)
* venue_footfall     - visitors per year / month to a mall, attraction or district
* new_homes_or_offices - homes, offices, hotel rooms or residents being added nearby
* transit_ridership  - riders at a nearby metro / tram station
* traffic_count      - vehicles per day / hour on the roads here

Pipeline::

    search (Claude + web search, per location, bounded)  ->  validate  ->  store  ->  group
           ->  per campaign: events inside its window  ->  extra people passing each face

Rules that keep the numbers defensible:

1. A fact is kept only when its quote contains the number (35,000 / 35k / 35 thousand) and its
   URL is one the web search actually returned. Everything else is stored as filtered out,
   with the reason, so an analyst can see what was dropped.
2. The AI only reads numbers that sources state. Turning attendance into people passing a
   billboard uses config ASSUMPTIONS (``news_event_pass_share``, ``news_audience_match_share``,
   ``event_max_daily_change``), never an AI estimate.
3. Facts are stored without any campaign baked in. Each campaign filters them by its own window
   when the page renders.
4. Only event attendance is modelled. Footfall, new homes and ridership are shown as evidence
   with their source, not turned into reach.

Facts live in ``data/signals/people.json``; planners can add facts by hand in
``data/inputs/people_facts.yaml``. The dashboard only reads these files, so it stays fast.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .config import DATA_DIR, INPUT_DIR, Campaign, Params, Placement, PlacementConfig, env_key

log = logging.getLogger(__name__)

PEOPLE_PATH = DATA_DIR / "signals" / "people.json"
MANUAL_PEOPLE_PATH = INPUT_DIR / "people_facts.yaml"

Kind = Literal["event_attendance", "venue_footfall", "new_homes_or_offices", "transit_ridership", "traffic_count"]
KINDS: dict[str, dict] = {
    "event_attendance": {"icon": "🎟️", "label": "Event crowd"},
    "venue_footfall": {"icon": "🛍️", "label": "Visitors"},
    "new_homes_or_offices": {"icon": "🏗️", "label": "New homes & offices"},
    "transit_ridership": {"icon": "🚇", "label": "Metro riders"},
    "traffic_count": {"icon": "🚗", "label": "Traffic count"},
}
TAGS = ["cars", "property", "shopping", "luxury", "business", "families", "sports", "culture", "general"]


CITY_WIDE = {"dubai", "uae", "united_arab_emirates", "dubai_wide", "all_of_dubai"}


def derived_tags(kind: str, what: str, tags: list[str]) -> list[str]:
    """Tags implied by what a number is: new homes are property evidence, mall crowds are shopping."""
    out = set(tags)
    if kind == "new_homes_or_offices":
        out.add("property")
    if kind in ("venue_footfall", "event_attendance") and re.search(r"\b(mall|souk|market|outlet|shopping)\b", what, re.I):
        out.add("shopping")
    return sorted(out)


# --------------------------------------------------------------------------- the fact


class PeopleFact(BaseModel):
    kind: Kind
    what: str                                   # event or venue name
    place: str = ""                             # one of the tracked nearby places
    value: float = Field(gt=0)
    unit: str = "people"
    period: Literal["event", "hour", "day", "week", "month", "year", "total"] = "event"
    event_start: date | None = None
    event_end: date | None = None
    figure_year: int | None = None              # the year the number refers to (last edition, etc.)
    tags: list[str] = Field(default_factory=lambda: ["general"])
    quote: str = ""
    source_url: str = ""
    source_title: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    note: str = ""                              # caveats: edition, capacity vs count, etc.
    measure: Literal["count", "expected", "capacity"] = "count"  # counted, announced/expected, or venue capacity
    near: list[str] = Field(default_factory=list)  # tracked places the crowd is at or passes through (e.g. a run route)

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, v):
        tags = [str(t).lower() for t in (v or [])]
        return [t for t in tags if t in TAGS] or ["general"]

    @field_validator("event_start", "event_end", mode="before")
    @classmethod
    def _blank_date(cls, v):
        return v or None


# --------------------------------------------------------------------------- validation

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|thousand|m|mn|million|bn|billion|lakh)?(?![\w])",
                  re.I)
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "lakh": 1e5}


def numbers_in(text: str) -> list[float]:
    """Every number a sentence states, with 35k / 1.2 million style multipliers applied."""
    out = []
    for m in _NUM.finditer(text or ""):
        base = float(m.group(1).replace(",", ""))
        mult = _MULT.get((m.group(2) or "").lower(), 1.0)
        out.append(base * mult)
    return out


def quote_has_number(value: float, quote: str) -> bool:
    """True when the quote states this value (within rounding: 1 %)."""
    return any(abs(n - value) <= max(1.0, 0.01 * value) for n in numbers_in(quote))


def check_fact(fact: PeopleFact, seen_urls: set[str] | None) -> str | None:
    """Reason to filter the fact out, or None when it passes. ``seen_urls`` None = manual entry."""
    if not fact.quote.strip():
        return "no quote from the source"
    if not quote_has_number(fact.value, fact.quote):
        return "the quote does not state this number"
    if seen_urls is not None:
        if not fact.source_url:
            return "no source link"
        if _norm_url(fact.source_url) not in {_norm_url(u) for u in seen_urls}:
            return "source link was not among the pages the search returned"
    return None


def _norm_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").strip()).rstrip("/").lower()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def fact_id(f: PeopleFact) -> str:
    raw = f"{f.kind}|{_slug(f.what)}|{f.value:.0f}|{_norm_url(f.source_url)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def short_name(what: str) -> str:
    """'Dubai Ride 2026 (previous edition), record' -> 'Dubai Ride' (for grouping only)."""
    name = re.split(r"[(,;:]| - | – ", what or "")[0]
    name = re.sub(r"\b(19|20)\d{2}\b|\bprevious edition\b|\bedition\b", "", name, flags=re.I)
    return _slug(name)


def group_key(f: dict) -> str:
    """One real-world number = same kind, same thing, same edition (dates or year), same period."""
    if f.get("event_start"):            # a dated crowd: same thing on the same day is one number
        when = f["event_start"]
    elif f["kind"] == "event_attendance":
        when = str(f["figure_year"]) if f.get("figure_year") else ""
    else:
        when = f.get("period", "")
    return f"{f['kind']}|{short_name(f['what'])}|{when}"


# --------------------------------------------------------------------------- placements


def place_index(pcfg: PlacementConfig) -> dict[str, list[str]]:
    """Slugged place name -> placement ids that see its crowds."""
    idx: dict[str, list[str]] = {}
    for p in pcfg.placements:
        names = list(p.nearby_places) + [a.strip() for a in p.area.split("/")] + [p.label]
        for n in names:
            if n:
                idx.setdefault(_slug(n), [])
                if p.id not in idx[_slug(n)]:
                    idx[_slug(n)].append(p.id)
    return idx


def placements_for(place: str, what: str, pcfg: PlacementConfig, kind: str = "") -> list[str]:
    idx = place_index(pcfg)
    hit = idx.get(_slug(place))
    if hit:
        return list(hit)
    if kind != "traffic_count" and any(_slug(p.corridor) == _slug(place) for p in pcfg.placements):
        return []  # a crowd "on Sheikh Zayed Road" is not a crowd at every face along it
    # fall back to a tracked place named inside the free text ("Dubai Marina Mall", "at DWTC")
    text = _slug(f"{place} {what}")
    hits = sorted({pid for name, pids in idx.items() if len(name) >= 4 and name in text for pid in pids})
    if hits:
        return hits
    return sorted(p.id for p in pcfg.placements if _slug(p.corridor) and _slug(p.corridor) == _slug(place))


# --------------------------------------------------------------------------- store


@dataclass
class PeopleStore:
    facts: dict[str, dict] = field(default_factory=dict)     # fact id -> fact + status / reason / placements
    searches: dict[str, str] = field(default_factory=dict)   # search key -> date last searched
    updated_at: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "PeopleStore":
        path = path or PEOPLE_PATH
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(raw.get("facts", {}), raw.get("searches", {}), raw.get("updated_at", ""))

    def save(self, path: Path | None = None) -> None:
        path = path or PEOPLE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(json.dumps({"updated_at": self.updated_at, "searches": self.searches, "facts": self.facts},
                                   indent=1, ensure_ascii=False, default=str))

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.facts.values():
            out[f["status"]] = out.get(f["status"], 0) + 1
        return out

    def add(self, fact: PeopleFact, reason: str | None, placements: list[str], search: str, source: str) -> str:
        fid = fact_id(fact)
        prev = self.facts.get(fid, {})
        self.facts[fid] = {**fact.model_dump(mode="json"), "id": fid, "placements": placements,
                           "status": "kept" if reason is None else "filtered", "reason": reason or "",
                           "search": search, "source": source,
                           "found_at": prev.get("found_at") or date.today().isoformat(),
                           "enabled": prev.get("enabled", True)}
        return fid


def load_manual_facts(pcfg: PlacementConfig) -> list[dict]:
    """Facts a planner typed in. Same quote rule; no search-URL rule."""
    if not MANUAL_PEOPLE_PATH.exists():
        return []
    rows = (yaml.safe_load(MANUAL_PEOPLE_PATH.read_text()) or {}).get("facts") or []
    out = []
    for r in rows:
        try:
            f = PeopleFact.model_validate({"confidence": 1.0, **r})
        except ValidationError as exc:
            log.warning("Skipped manual people fact: %s", exc.errors()[:1])
            continue
        reason = check_fact(f, None)
        pids = r.get("placements") or placements_for(f.place, f.what, pcfg, f.kind)
        out.append({**f.model_dump(mode="json"), "id": "m-" + fact_id(f), "placements": pids,
                    "status": "kept" if reason is None else "filtered", "reason": reason or "",
                    "search": "manual", "source": "planner", "found_at": "", "enabled": bool(r.get("enabled", True))})
    return out


def all_facts(pcfg: PlacementConfig, store: PeopleStore | None = None) -> list[dict]:
    """Online + manual facts from disk (no network)."""
    store = store or PeopleStore.load()
    return list(store.facts.values()) + load_manual_facts(pcfg)


# --------------------------------------------------------------------------- Claude + web search

SEARCH_SYSTEM = (
    "You collect sourced numbers about how many people visit places in Dubai, for an outdoor-advertising "
    "planner. You only report numbers that a page you found states, with the exact sentence. You never "
    "estimate, round or compute a number. Answer with JSON only."
)

SEARCH_PROMPT = """Today is {today}. Our campaigns (a car launch, a property launch and a shopping festival) run
between {start} and {end}.

Find NUMBERS that show how many people are at, or come to, this location in Dubai: {label}
(nearby places: {places}).

Look for:
- event_attendance: events at these places between {start} and {end} (exhibitions, concerts, races,
  festivals, motor shows, property shows, shopping festivals, sports). Give the announced or expected attendance. If this year's
  figure is not published, give the most recent edition's attendance, its year in figure_year, and this
  year's dates in event_start / event_end.
- venue_footfall: visitors per year or month to a mall, attraction or district here.
- new_homes_or_offices: homes, offices, hotel rooms or residents being added here.
- transit_ridership: riders at a nearby metro or tram station.
- traffic_count: vehicles per day or hour on the roads here.
Tag cars (motor shows, car launches, supercar meets) "cars", property (property shows, new communities,
residents moving in) "property", and shopping (shopping festivals, mall crowds, big sales) "shopping".
{hints}
How to search: run several different searches (for example "<place> visitors per year",
"<place> events {month} attendance", "<place> new residential units", "<nearest metro station> ridership").
Aim for 4 to 8 facts.

Rules: every fact must come from a page this search returned. "quote" is the sentence from that page
that contains the number, copied word for word. Skip anything you cannot quote. Return at most 8 facts,
the ones most useful for judging how many people pass this location.

JSON only:
{{"facts": [{{"kind": "event_attendance" | "venue_footfall" | "new_homes_or_offices" | "transit_ridership" | "traffic_count",
  "what": "<short official name only, e.g. 'Dubai Ride' or 'Mall of the Emirates'>",
  "place": "<one of: {places}, or the place the source names>",
  "near": [<places from this list the crowd is at or passes through, e.g. a race route: {places}>],
  "value": <number>, "unit": "people" | "visitors" | "riders" | "vehicles" | "homes" | "offices" | "hotel rooms" | "residents" | "employees",
  "period": "event" | "hour" | "day" | "week" | "month" | "year" | "total" (total = a count that exists, e.g. residents),
  "event_start": "YYYY-MM-DD" or null, "event_end": "YYYY-MM-DD" or null, "figure_year": <int> or null,
  "tags": ["cars" | "property" | "shopping" | "luxury" | "business" | "families" | "sports" | "culture" | "general"],
  "quote": "<exact sentence>", "source_url": "<url>", "source_title": "<page title>", "confidence": 0.0-1.0,
  "measure": "count" (people actually counted) | "expected" (announced or forecast) | "capacity" (how many a venue or road can hold, not a count),
  "note": "<= 15 words of caveats: which edition, capacity not a count, whole road not this stretch"}}]}}"""

# One Dubai-wide search per campaign industry (the first news tag of each campaign), with a headline filter.
TOPICS = {
    "cars": ("car events anywhere in Dubai (motor shows, car festivals, supercar meets, car launches)",
             r"\b(car|cars|motor|auto|supercar|vehicle)\b"),
    "property": ("property events and new homes anywhere in Dubai (property shows such as Cityscape, new "
                 "communities handing over homes, residents moving in, property-show visitor numbers)",
                 r"\b(property|real estate|homes|residential|off-plan|developer|cityscape)\b"),
    "shopping": ("shopping events anywhere in Dubai (Dubai Shopping Festival, mall sales, retail festivals, "
                 "mall visitor numbers)",
                 r"\b(shopping|mall|retail|sale|souk|outlet)\b"),
}


@dataclass
class Search:
    key: str            # placement id or a topic in TOPICS
    label: str
    places: list[str]


def searches_for(pcfg: PlacementConfig) -> list[Search]:
    out = [Search(p.id, f"{p.label} ({p.name})", list(p.nearby_places) or [p.area]) for p in pcfg.placements]
    every = sorted({n for p in pcfg.placements for n in p.nearby_places})
    topics = [t for c in pcfg.campaign_options() for t in c.news_tags[:1] if t in TOPICS]
    out += [Search(t, TOPICS[t][0], every) for t in dict.fromkeys(topics)]
    return out


def search_window(pcfg: PlacementConfig) -> tuple[date, date]:
    camps = pcfg.campaign_options()
    return min(c.plan_start for c in camps), max(c.plan_end for c in camps)


def _hint_lines(headlines: list[str]) -> str:
    if not headlines:
        return ""
    lines = "\n".join(f"- {h}" for h in headlines[:15])
    return f"\nRecent headlines about this location (leads worth checking for numbers):\n{lines}\n"


def claude_people_search(search: Search, start: date, end: date, headlines: list[str]
                         ) -> tuple[list[dict], set[str]] | None:
    """One Claude call with web search. Returns raw fact dicts and the URLs the search returned."""
    if not env_key("ANTHROPIC_API_KEY"):
        return None
    from .narrative import MODEL, claude_client

    prompt = SEARCH_PROMPT.format(today=date.today().isoformat(), start=start, end=end, label=search.label,
                                  month=start.strftime("%B %Y"),
                                  places=", ".join(search.places), hints=_hint_lines(headlines))
    messages = [{"role": "user", "content": prompt}]
    urls: set[str] = set()
    try:
        client = claude_client()
        for _ in range(3):  # a long server-tool turn may pause; re-send to continue
            response = client.beta.messages.create(
                model=MODEL, max_tokens=12000, system=SEARCH_SYSTEM, output_config={"effort": "medium"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", messages=messages)
            for block in response.content:
                if block.type == "web_search_tool_result" and isinstance(block.content, list):
                    urls.update(r.url for r in block.content if getattr(r, "type", "") == "web_search_result")
            if response.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
    except Exception as exc:  # API, network or SDK error
        log.warning("People search failed for %s: %s", search.key, exc)
        return None
    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    return list(data.get("facts") or []), urls


def _headlines_for(key: str) -> list[str]:
    """Recent headlines from the road-signal ledger, used as leads for the search."""
    try:
        from .signals import Ledger

        arts = Ledger.load().articles.values()
    except Exception:
        return []
    rows = sorted((a for a in arts if key in a.get("placements", []) or key in TOPICS),
                  key=lambda a: a.get("published", ""), reverse=True)
    if key in TOPICS:
        rows = [a for a in rows if re.search(TOPICS[key][1], a["title"], re.I)]
    return [f"{a.get('published', '')[:10]} | {a['title']}" for a in rows]


def refresh(pcfg: PlacementConfig, force: bool = False, search=None, only: list[str] | None = None) -> PeopleStore:
    """Search every location (once a day unless ``force``), validate, store. ``search`` is injectable."""
    search = search or claude_people_search
    store = PeopleStore.load()
    start, end = search_window(pcfg)
    today = date.today().isoformat()
    for s in searches_for(pcfg):
        if only and s.key not in only:
            continue
        if not force and store.searches.get(s.key) == today:
            continue
        res = search(s, start, end, _headlines_for(s.key))
        if res is None:
            continue
        raw, urls = res
        for row in raw:
            try:
                fact = PeopleFact.model_validate(row)
            except ValidationError as exc:
                log.info("Dropped unparseable people fact: %s", exc.errors()[:1])
                continue
            reason = check_fact(fact, urls)
            pids = sorted(set(placements_for(fact.place, fact.what, pcfg, fact.kind))
                          | {pid for n in fact.near for pid in place_index(pcfg).get(_slug(n), [])})
            store.add(fact, reason, pids, s.key, "online")
        store.searches[s.key] = today
    store.save()
    return store


# --------------------------------------------------------------------------- grouping


@dataclass
class FactGroup:
    """One real-world number, seen in one or more sources (low / base / high across sources)."""

    key: str
    kind: str
    what: str
    place: str
    unit: str
    period: str
    value: float
    low: float
    high: float
    event_start: date | None
    event_end: date | None
    figure_year: int | None
    tags: list[str]
    placements: list[str]
    sources: list[dict]          # {title, url, quote}
    confidence: float
    note: str = ""
    measure: str = "count"

    @property
    def icon(self) -> str:
        return KINDS[self.kind]["icon"]


def group_facts(facts: list[dict], kept_only: bool = True) -> list[FactGroup]:
    groups: dict[str, list[dict]] = {}
    for f in facts:
        if kept_only and (f.get("status") != "kept" or not f.get("enabled", True)):
            continue
        groups.setdefault(group_key(f), []).append(f)
    out = []
    for key, rows in groups.items():
        vals = [float(r["value"]) for r in rows]
        lead = max(rows, key=lambda r: r.get("confidence", 0))
        d = lambda v: date.fromisoformat(v) if v else None  # noqa: E731
        out.append(FactGroup(
            key=key, kind=lead["kind"], what=lead["what"], place=lead.get("place", ""), unit=lead.get("unit", ""),
            period=lead.get("period", "event"), value=statistics.median(vals), low=min(vals), high=max(vals),
            event_start=d(lead.get("event_start")), event_end=d(lead.get("event_end") or lead.get("event_start")),
            figure_year=lead.get("figure_year"),
            tags=derived_tags(lead["kind"], lead["what"], sorted({t for r in rows for t in r.get("tags", [])})),
            placements=([] if _slug(lead.get("place", "")) in CITY_WIDE   # a city-wide total is not one board's crowd
                        else sorted({p for r in rows for p in r.get("placements", [])})),
            sources=[{"title": r.get("source_title") or r.get("source", ""), "url": r.get("source_url", ""),
                      "quote": r.get("quote", "")} for r in rows],
            confidence=max(r.get("confidence", 0) for r in rows), note=lead.get("note", ""),
            measure=lead.get("measure", "count")))
    return out


def merge_by_name(groups: list[FactGroup]) -> list[FactGroup]:
    """One card per thing (e.g. two editions of the same motor show): newest usable figure leads.

    Used for evidence lists only; modelled crowd events keep their own dated groups.
    """
    this_year = date.today().year
    by: dict[tuple, list[FactGroup]] = {}
    for g in groups:
        by.setdefault((g.kind, short_name(g.what), g.period if g.kind != "event_attendance" else ""), []).append(g)
    out = []
    for rows in by.values():
        if len(rows) == 1:
            out.append(rows[0])
            continue
        lead = max(rows, key=lambda g: (g.measure != "capacity",
                                        not (g.figure_year and g.figure_year < this_year - 2),
                                        g.figure_year or 0, g.confidence, g.value))
        seen, sources = set(), []
        for g in [lead] + [r for r in rows if r is not lead]:
            for src in g.sources:
                if src["url"] not in seen:
                    seen.add(src["url"])
                    sources.append(src)
        out.append(FactGroup(**{**lead.__dict__, "low": min(g.low for g in rows), "high": max(g.high for g in rows),
                                "sources": sources, "tags": sorted({t for g in rows for t in g.tags}),
                                "placements": sorted({p for g in rows for p in g.placements})}))
    return out


# --------------------------------------------------------------------------- per campaign


@dataclass
class CrowdEvent:
    group: FactGroup
    days_in_window: int
    visitors_in_window: float
    extra_people: float          # extra people passing the face (ESTIMATE, config shares)
    extra_low: float
    extra_high: float
    extra_target: float          # of whom in the campaign audience
    matches_campaign: bool
    capped: bool


@dataclass
class LocationPulse:
    pid: str
    events: list[CrowdEvent]                 # crowd events inside the campaign window (modelled)
    later: list[FactGroup]                   # dated events outside the window (context)
    context: list[FactGroup]                 # footfall, new homes, ridership, traffic (evidence only)

    @property
    def extra_people(self) -> float:
        return sum(e.extra_people for e in self.events)

    @property
    def extra_target(self) -> float:
        return sum(e.extra_target for e in self.events)

    @property
    def match_events(self) -> list[CrowdEvent]:
        return [e for e in self.events if e.matches_campaign]


def _overlap_days(a0: date, a1: date, b0: date, b1: date) -> int:
    return max(0, (min(a1, b1) - max(a0, b0)).days + 1)


def crowd_event(g: FactGroup, campaign: Campaign, params: Params, people_day: float, interest_share: float
                ) -> CrowdEvent | None:
    """Attendance inside the campaign window -> extra people passing one face (config shares, capped)."""
    dated_crowd = g.kind == "event_attendance" or (g.kind == "transit_ridership" and g.period in ("event", "day"))
    if not dated_crowd or g.event_start is None or g.measure == "capacity":
        return None
    end = g.event_end or g.event_start
    days = _overlap_days(g.event_start, end, campaign.plan_start, campaign.plan_end)
    if days == 0:
        return None
    total_days = (end - g.event_start).days + 1
    per_visit = (lambda v: v * days) if g.period == "day" else (lambda v: v * days / total_days)
    visitors, v_low, v_high = per_visit(g.value), per_visit(g.low), per_visit(g.high)
    cap = params.base("event_max_daily_change") * people_day * days
    share = {s: params.get("news_event_pass_share", s) for s in ("low", "base", "high")}
    extra = min(visitors * share["base"], cap)
    low, high = min(v_low * share["low"], cap), min(v_high * share["high"], cap)
    match = bool(set(g.tags) & set(campaign.news_tags))
    target_share = params.base("news_audience_match_share") if match else interest_share
    return CrowdEvent(g, days, visitors, extra, low, high, extra * target_share, match,
                      capped=visitors * share["base"] > cap)


def campaign_pulse(groups: list[FactGroup], pcfg: PlacementConfig, campaign: Campaign, params: Params,
                   people_day: dict[str, float], interest_share: dict[str, float]) -> dict[str, LocationPulse]:
    out = {}
    for p in pcfg.placements:
        mine = [g for g in groups if p.id in g.placements]
        events, later, context = [], [], []
        for g in mine:
            if g.kind == "event_attendance" or (g.kind == "transit_ridership" and g.event_start):
                ev = crowd_event(g, campaign, params, people_day.get(p.id, 0.0), interest_share.get(p.id, 1.0))
                (events.append(ev) if ev else later.append(g))
            else:
                context.append(g)
        events.sort(key=lambda e: e.group.event_start)
        out[p.id] = LocationPulse(p.id, events, merge_by_name(later), merge_by_name(context))
    return out


def pulse_for_results(res, pcfg: PlacementConfig, campaign: Campaign, params: Params,
                      facts: list[dict] | None = None) -> dict[str, LocationPulse]:
    """Convenience wrapper over pipeline Results."""
    facts = all_facts(pcfg) if facts is None else facts
    people_day = {pid: r.metrics["people_day"].value for pid, r in res.placements.items()}
    shares = {pid: r.profile.interest_share.value for pid, r in res.placements.items()}
    return campaign_pulse(group_facts(facts), pcfg, campaign, params, people_day, shares)


def plan_with_crowds(res, pulse: dict[str, LocationPulse], boards: int):
    """Re-run the plan builder with each face's crowd-event people added. Returns (plan, items)."""
    import dataclasses

    from . import duplication

    items = [dataclasses.replace(it, unique=it.unique + pulse[it.id].extra_people,
                                 relevant=it.relevant + pulse[it.id].extra_target)
             if it.id in pulse else it for it in res.plan_items]
    return duplication.best_plan(items, res.overlap, boards), items
