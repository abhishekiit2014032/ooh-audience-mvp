"""Online signals -> dated events -> traffic adjustments for the campaign forecast.

Pipeline (run by the "Refresh signals" button or ``scripts/refresh_signals.py``, never on a
slider change):

1. **Collect** headlines per placement (Google News, GDELT; see :mod:`ooh.news`).
2. **Ledger**: every article is stored once in ``data/signals/ledger.json`` with first/last seen,
   the placements whose queries found it, and a status:

   * ``applied``: linked to an event inside the campaign window
   * ``pending``: looks relevant but has no date, or no extractor (no Claude key)
   * ``rejected``: with a reason (off-location, no traffic/audience event, outside the window,
     unparseable). Rejected items stay, so the noise filter is auditable.

3. **Extract** (new articles only, then frozen): Claude reads the headline and returns the event
   type, dates, hours, corridor / areas and its confidence. Responses are validated with pydantic.
   Undated candidates can be **enriched** with Claude's web search tool, which must cite its sources.
4. **De-duplicate** into events keyed by (type, corridor or area, date). Five articles about one
   closure make one event with five sources.
5. **Apply** (in :func:`campaign_forecast`): only events switched on, dated inside the campaign
   window, on the placement's corridor (closures, roadworks) or area (major events). The size of
   each effect comes from ``config/assumptions.yaml`` (ASSUMPTION), never from the extractor.

Manual events can be added in ``data/inputs/events.yaml`` without any key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from .config import DATA_DIR, INPUT_DIR, Campaign, Params, Placement, PlacementConfig, env_key
from .metrics import Metric

log = logging.getLogger(__name__)

SIGNALS_DIR = DATA_DIR / "signals"
LEDGER_PATH = SIGNALS_DIR / "ledger.json"
MANUAL_EVENTS_PATH = INPUT_DIR / "events.yaml"
EVENT_TYPES = ("full_closure", "partial_closure", "roadworks", "major_event")


# --------------------------------------------------------------------------- extraction schema


class Extraction(BaseModel):
    """What the extractor may say about one headline. Effect sizes are deliberately absent."""

    id: int
    relevant: bool
    event_type: Literal["full_closure", "partial_closure", "roadworks", "major_event", "opening", "none"]
    event_date: date | None = None
    end_date: date | None = None
    start_hour: int | None = Field(default=None, ge=0, le=23)
    end_hour: int | None = Field(default=None, ge=1, le=24)
    corridor: str | None = None
    areas: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    placements: list[str] | None = None   # set by web-search enrichment when the source names the section
    stretch: str = ""

    @field_validator("reason")
    @classmethod
    def _short(cls, v: str) -> str:
        return v[:160]


class Enrichment(BaseModel):
    found: bool
    event_date: date | None = None
    end_date: date | None = None
    start_hour: int | None = Field(default=None, ge=0, le=23)
    end_hour: int | None = Field(default=None, ge=1, le=24)
    stretch: str = ""                 # the affected section, as the source names it
    placements: list[str] | None = None  # our faces inside that section; None = unknown
    note: str = ""


# --------------------------------------------------------------------------- ledger


@dataclass
class Ledger:
    articles: dict[str, dict] = field(default_factory=dict)
    events: dict[str, dict] = field(default_factory=dict)
    updated_at: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Ledger":
        path = path or LEDGER_PATH
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(data.get("articles", {}), data.get("events", {}), data.get("updated_at", ""))

    def save(self, path: Path | None = None) -> None:
        path = path or LEDGER_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"updated_at": self.updated_at, "articles": self.articles,
                                   "events": self.events}, indent=1, default=str))
        tmp.replace(path)

    def counts(self) -> dict[str, int]:
        out = {"applied": 0, "pending": 0, "rejected": 0}
        for a in self.articles.values():
            out[a["status"]] = out.get(a["status"], 0) + 1
        return out


def article_id(title: str, url: str) -> str:
    norm = re.sub(r"[^a-z0-9 ]", "", title.lower())[:90]
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def event_key(event_type: str, scope_name: str, day: date) -> str:
    return f"{event_type}|{_slug(scope_name)}|{day.isoformat()}"


# --------------------------------------------------------------------------- matching


def corridor_names(pcfg: PlacementConfig) -> list[str]:
    return sorted({p.corridor for p in pcfg.placements})


def area_names(pcfg: PlacementConfig) -> list[str]:
    names = set()
    for p in pcfg.placements:
        names.update(a.strip() for a in p.area.split("/"))
    return sorted(names)


def affects(event: dict, placement: Placement, cfg_types: dict) -> bool:
    """Closures and roadworks hit a corridor; major events hit an area.

    When a cited source names the affected section, only the faces inside it are hit.
    """
    if isinstance(event.get("placements"), list):
        return placement.id in event["placements"]
    scope = cfg_types[event["type"]].scope if event["type"] in cfg_types else "corridor"
    if scope == "corridor":
        return _slug(event.get("corridor") or "") == _slug(placement.corridor)
    areas = {_slug(a) for a in placement.area.split("/")}
    return bool(areas & {_slug(a) for a in event.get("areas", [])})


# --------------------------------------------------------------------------- classify one article


def _status_from_extraction(ex: Extraction, campaign: Campaign) -> tuple[str, str]:
    if not ex.relevant:
        return "rejected", ex.reason or "not about the placements' corridors or areas"
    if ex.event_type in ("none", "opening"):
        return "rejected", "no dated traffic or audience event" if ex.event_type == "none" else \
            "opening: context only, no traffic effect modelled"
    if ex.event_date is None:
        return "pending", "relevant event without a stated date"
    end = ex.end_date or ex.event_date
    if end < campaign.plan_start or ex.event_date > campaign.plan_end:
        return "rejected", f"outside the campaign window ({campaign.plan_start} to {campaign.plan_end})"
    return "applied", ex.reason or "dated event inside the campaign window"


def link_event(ledger: Ledger, aid: str, ex: Extraction, min_conf: float, source: str) -> str:
    """Attach an article to its event, creating the event on first sight."""
    scope_name = ex.corridor if ex.event_type != "major_event" else (ex.areas[0] if ex.areas else "")
    key = event_key(ex.event_type, scope_name or "unknown", ex.event_date)
    ev = ledger.events.get(key)
    if ev is None:
        ev = ledger.events[key] = {
            "id": key, "type": ex.event_type, "corridor": ex.corridor, "areas": ex.areas,
            "date": ex.event_date.isoformat(), "end_date": (ex.end_date or ex.event_date).isoformat(),
            "start_hour": ex.start_hour, "end_hour": ex.end_hour, "confidence": ex.confidence,
            "articles": [], "citations": [], "source": source,
            "enabled": ex.confidence >= min_conf, "note": ex.reason,
            "placements": ex.placements, "stretch": ex.stretch,
        }
    if aid not in ev["articles"]:
        ev["articles"].append(aid)
    ev["confidence"] = max(ev["confidence"], ex.confidence)
    if ev.get("placements") is None and ex.placements is not None:
        ev["placements"], ev["stretch"] = ex.placements, ex.stretch
    for k in ("start_hour", "end_hour"):
        if ev.get(k) is None and getattr(ex, k) is not None:
            ev[k] = getattr(ex, k)
    return key


# --------------------------------------------------------------------------- Claude calls


EXTRACT_SYSTEM = (
    "You extract dated traffic and audience events from news headlines for an outdoor-advertising "
    "planner in Dubai. Use only what the headline and its publication date state or directly imply "
    "(for example 'this Sunday' relative to the publication date). Never guess a date or time. "
    "Never estimate how big an effect is. Answer with JSON only."
)

EXTRACT_PROMPT = """Today is {today}. Campaign window: {start} to {end}.
Corridors we track: {corridors}. Areas we track: {areas}.

Headlines (JSON list; index = id; each is "publication date | title (source)"):
{headlines}

For every headline return one item:
{{"items": [{{"id": <int>, "relevant": <true if it concerns one of the corridors or areas>,
  "event_type": "full_closure" | "partial_closure" | "roadworks" | "major_event" | "opening" | "none",
  "event_date": "YYYY-MM-DD" or null, "end_date": "YYYY-MM-DD" or null,
  "start_hour": 0-23 or null, "end_hour": 1-24 or null,
  "corridor": one of the tracked corridors or null, "areas": [tracked areas],
  "confidence": 0.0-1.0, "reason": "<= 15 words"}}]}}

full_closure = a road closed to cars (e.g. a cycling or running event on the road).
partial_closure = some lanes or exits closed, diversions. roadworks = construction or maintenance works.
major_event = an event that draws crowds to a tracked area. opening = a new building, mall or office."""


def _client():
    from .narrative import claude_client

    return claude_client()


def _parse_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def claude_extract(items: list[dict], pcfg: PlacementConfig) -> list[Extraction] | None:
    """One Claude call for a batch of headlines. None without a key or on any failure."""
    if not env_key("ANTHROPIC_API_KEY") or not items:
        return None
    from .narrative import MODEL

    c = pcfg.campaign
    prompt = EXTRACT_PROMPT.format(
        today=date.today().isoformat(), start=c.plan_start, end=c.plan_end,
        corridors=", ".join(corridor_names(pcfg)), areas=", ".join(area_names(pcfg)),
        headlines=json.dumps([f"{i.get('published', '')} | {i['title']} ({i.get('source', '')})" for i in items],
                             ensure_ascii=False))
    try:
        response = _client().beta.messages.create(
            model=MODEL, max_tokens=8000, system=EXTRACT_SYSTEM, output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}])
    except Exception as exc:  # API, network or SDK error
        log.warning("Signal extraction failed: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    data = _parse_json("".join(b.text for b in response.content if b.type == "text"))
    if not data:
        return None
    out = []
    for row in data.get("items", []):
        try:
            out.append(Extraction.model_validate(row))
        except ValidationError as exc:
            log.info("Dropped unparseable extraction: %s", exc.errors()[:1])
    return out


ENRICH_PROMPT = """An outdoor-advertising planner needs the exact date, hours and road section of this event in Dubai:
"{title}" (published {published}).

Our billboard faces (id: location): {faces}

Search the web. Use only what reliable pages (RTA, government, major news) state. Then answer with JSON only:
{{"found": true/false, "event_date": "YYYY-MM-DD" or null, "end_date": "YYYY-MM-DD" or null,
  "start_hour": 0-23 or null, "end_hour": 1-24 or null,
  "stretch": "<the affected road section as the source names it>",
  "placements": [ids of our faces that lie inside that section] or null if the section is not stated,
  "note": "<= 25 words, what the source says"}}"""


def faces_text(pcfg: PlacementConfig | None) -> str:
    if pcfg is None:
        return "unknown"
    return "; ".join(f"{p.id}: {p.name} ({p.area}, lat {p.lat:.4f}, lon {p.lon:.4f})" for p in pcfg.placements)


def claude_enrich(title: str, published: str, pcfg: PlacementConfig | None = None) -> tuple[Enrichment, list[dict]] | None:
    """Look up an undated event with Claude's web search tool. Returns the fields and cited pages."""
    if not env_key("ANTHROPIC_API_KEY"):
        return None
    from .narrative import MODEL

    messages = [{"role": "user", "content": ENRICH_PROMPT.format(title=title, published=published,
                                                                 faces=faces_text(pcfg))}]
    citations: list[dict] = []
    try:
        client = _client()
        for _ in range(3):  # a long server-tool turn may pause; re-send to continue
            response = client.beta.messages.create(
                model=MODEL, max_tokens=4000, output_config={"effort": "low"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", messages=messages)
            for block in response.content:
                if block.type == "web_search_tool_result" and isinstance(block.content, list):
                    citations += [{"title": r.title, "url": r.url} for r in block.content
                                  if getattr(r, "type", "") == "web_search_result"]
            if response.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
    except Exception as exc:
        log.warning("Signal enrichment failed: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    data = _parse_json("".join(b.text for b in response.content if b.type == "text"))
    try:
        enr = Enrichment.model_validate(data or {})
    except ValidationError:
        return None
    seen, unique = set(), []
    for c in citations:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)
    return enr, unique[:6]


# --------------------------------------------------------------------------- refresh


def refresh(pcfg: PlacementConfig, params: Params, use_gdelt: bool = True, enrich_limit: int = 4,
            fetch=None, extract=None, enrich=None) -> Ledger:
    """Collect, extract (new articles only), enrich undated candidates and rebuild events.

    ``fetch`` / ``extract`` / ``enrich`` are injectable for tests.
    """
    from .news import fetch_news

    fetch = fetch or (lambda p: fetch_news(p, use_gdelt=use_gdelt)[0])
    extract = extract or (lambda items: claude_extract(items, pcfg))
    enrich = enrich or (lambda title, published: claude_enrich(title, published, pcfg))
    known_ids = {p.id for p in pcfg.placements}
    min_conf = params.base("event_min_confidence")
    ledger = Ledger.load()
    now = date.today().isoformat()

    # 1. collect
    for p in pcfg.placements:
        for item in fetch(p):
            d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            aid = article_id(d["title"], d.get("url", ""))
            rec = ledger.articles.get(aid)
            if rec is None:
                rec = ledger.articles[aid] = {**d, "id": aid, "first_seen": now, "placements": [],
                                              "status": "pending", "reason": "awaiting extraction",
                                              "extraction": None, "event": None}
            rec["last_seen"] = now
            if p.id not in rec["placements"]:
                rec["placements"].append(p.id)

    # 2. extract new articles only (then frozen)
    todo = [a for a in ledger.articles.values() if a["extraction"] is None]
    for start in range(0, len(todo), 30):
        batch = todo[start:start + 30]
        result = extract(batch)
        if result is None:
            for a in batch:
                a["status"], a["reason"] = "pending", "no extractor (set ANTHROPIC_API_KEY) or extraction failed"
            continue
        by_idx = {ex.id: ex for ex in result}
        for idx, a in enumerate(batch):
            ex = by_idx.get(idx)
            if ex is None:
                a["status"], a["reason"], a["extraction"] = "rejected", "unparseable extraction", {}
                continue
            a["extraction"] = ex.model_dump(mode="json")

    # 3. enrich with web search (bounded): one look-up per candidate event that lacks a date or hours
    groups: dict[tuple, list[dict]] = {}
    for a in ledger.articles.values():
        ex = a.get("extraction") or {}
        if not (ex.get("relevant") and ex.get("event_type") in EVENT_TYPES):
            continue
        if ex.get("event_date") and ex.get("start_hour") is not None and "placements" in ex:
            continue
        scope = ex.get("corridor") or ",".join(ex.get("areas") or [])
        groups.setdefault((ex["event_type"], _slug(scope), ex.get("event_date")), []).append(a)
    enriched = 0
    for members in groups.values():
        done = next((m["enrichment"] for m in members if m.get("enrichment")), None)
        if done is None:
            if enriched >= enrich_limit:
                continue
            lead = max(members, key=lambda m: m.get("published", ""))
            res = enrich(lead["title"], lead.get("published", ""))
            enriched += 1
            if not res:
                continue
            enr, cites = res
            done = {**enr.model_dump(mode="json"), "citations": cites}
        for m in members:
            m["enrichment"] = done
            ex = m["extraction"]
            if done.get("found"):
                for k in ("event_date", "end_date", "start_hour", "end_hour"):
                    if ex.get(k) is None and done.get(k) is not None:
                        ex[k] = done[k]
                ids = done.get("placements")
                if isinstance(ids, list):
                    ex["placements"] = [i for i in ids if i in known_ids]
                    ex["stretch"] = done.get("stretch", "")

    rebuild_events(ledger, pcfg, min_conf)
    ledger.save()
    return ledger


def rebuild_events(ledger: Ledger, pcfg: PlacementConfig, min_conf: float) -> None:
    """Re-derive statuses and events from frozen extractions. Keeps planner on/off choices."""
    previous = {k: v.get("enabled") for k, v in ledger.events.items() if v.get("source") != "manual"}
    ledger.events = {k: v for k, v in ledger.events.items() if v.get("source") == "manual"}
    for aid, a in ledger.articles.items():
        raw = a.get("extraction")
        if raw is None or raw == {}:
            continue
        try:
            ex = Extraction.model_validate(raw)
        except ValidationError:
            a["status"], a["reason"] = "rejected", "unparseable extraction"
            continue
        a["status"], a["reason"] = _status_from_extraction(ex, pcfg.campaign)
        a["event"] = None
        if a["status"] == "applied":
            key = link_event(ledger, aid, ex, min_conf, "online signals")
            a["event"] = key
            cites = (a.get("enrichment") or {}).get("citations", [])
            ev = ledger.events[key]
            ev["citations"] = (ev["citations"] + [c for c in cites if c not in ev["citations"]])[:8]
    for k, enabled in previous.items():
        if k in ledger.events and enabled is not None:
            ledger.events[k]["enabled"] = enabled
    for ev in load_manual_events():
        ledger.events[ev["id"]] = ev


def load_manual_events() -> list[dict]:
    if not MANUAL_EVENTS_PATH.exists():
        return []
    rows = yaml.safe_load(MANUAL_EVENTS_PATH.read_text()) or {}
    out = []
    for r in rows.get("events", []) or []:
        day = date.fromisoformat(str(r["date"]))
        scope_name = r.get("corridor") or (r.get("areas") or [""])[0]
        out.append({
            "id": event_key(r["type"], scope_name, day), "type": r["type"], "corridor": r.get("corridor"),
            "areas": r.get("areas", []), "date": day.isoformat(),
            "end_date": str(r.get("end_date") or day.isoformat()), "start_hour": r.get("start_hour"),
            "end_hour": r.get("end_hour"), "confidence": 1.0, "articles": [], "citations": r.get("citations", []),
            "source": "manual", "enabled": bool(r.get("enabled", True)), "note": r.get("note", ""),
            "placements": r.get("placements"), "stretch": r.get("stretch", ""),
        })
    return out


# --------------------------------------------------------------------------- apply to the forecast


@dataclass
class CampaignForecast:
    days: list[date]
    baseline_daily: np.ndarray          # placement impressions per day, no events
    adjusted_daily: np.ndarray
    applied: list[dict]                 # events that moved this placement, with their day effect
    baseline: Metric
    adjusted: Metric
    unique_adjusted: Metric

    @property
    def delta(self) -> float:
        return self.adjusted.value - self.baseline.value


def _hour_mask(start: int | None, end: int | None, etype) -> np.ndarray:
    s = etype.default_start_hour if start is None else start
    e = etype.default_end_hour if end is None else end
    mask = np.zeros(24, dtype=bool)
    mask[s:max(s + 1, e)] = True
    return mask


def campaign_forecast(placement: Placement, campaign: Campaign, road_hourly: dict[str, np.ndarray],
                      other_daily: dict[str, float], unique_month: Metric, params: Params,
                      events: list[dict], overrides: dict[str, bool] | None = None) -> CampaignForecast:
    """Campaign-period impressions with event multipliers on the road part of each day.

    ``road_hourly`` holds 24 hourly road impressions per scenario; ``other_daily`` the part events
    do not touch (metro). Unique people scale with impressions: an ASSUMPTION, labelled as such.
    """
    overrides = overrides or {}
    types = params.cfg.event_types
    cap = params.base("event_max_daily_change")
    days = [campaign.plan_start + timedelta(d) for d in range((campaign.plan_end - campaign.plan_start).days + 1)]
    active = [e for e in events if overrides.get(e["id"], e.get("enabled", False)) and e["type"] in types
              and affects(e, placement, types)]

    def series(scenario: str) -> tuple[np.ndarray, np.ndarray, list[dict]]:
        hourly = road_hourly[scenario]
        base_day = float(hourly.sum()) + other_daily[scenario]
        base = np.full(len(days), base_day)
        adj = base.copy()
        hits = []
        for i, day in enumerate(days):
            mult = np.ones(24)
            todays = [e for e in active if date.fromisoformat(e["date"]) <= day <= date.fromisoformat(e["end_date"])]
            for e in todays:
                factor = params.base(types[e["type"]].factor_param)
                mult[_hour_mask(e.get("start_hour"), e.get("end_hour"), types[e["type"]])] *= factor
            if not todays:
                continue
            road = float((hourly * mult).sum())
            day_total = road + other_daily[scenario]
            change = np.clip(day_total / base_day - 1, -cap, cap) if base_day else 0.0
            adj[i] = base_day * (1 + change)
            for e in todays:
                hits.append({"event": e["id"], "type": e["type"], "date": day.isoformat(),
                             "change": float(change), "impressions_delta": float(adj[i] - base_day)})
        return base, adj, hits

    res = {s: series(s) for s in ("low", "base", "high")}
    base_b, adj_b, hits = res["base"]

    def metric(idx: int, label: str, source: str) -> Metric:
        return Metric(float(res["base"][idx].sum()), float(res["low"][idx].sum()), float(res["high"][idx].sum()),
                      label, source, "impressions/campaign")

    baseline = metric(0, unique_month.label, "Daily placement impressions x campaign days, no events")
    adjusted = metric(1, unique_month.label, f"Baseline with {len({h['event'] for h in hits})} news events applied")
    ratio = adjusted.value / baseline.value if baseline.value else 1.0
    unique_adj = Metric(unique_month.value * ratio, unique_month.low * ratio, unique_month.high * ratio,
                        "ESTIMATE", "Unique audience scaled with campaign impressions (ASSUMPTION: proportional)",
                        "people/month")
    return CampaignForecast(days, base_b, adj_b, hits, baseline, adjusted, unique_adj)


def active_events(ledger: Ledger | None = None) -> list[dict]:
    """Events on disk (online + manual). Fast: no network."""
    ledger = ledger or Ledger.load()
    manual = {e["id"]: e for e in load_manual_events()}
    return list({**ledger.events, **manual}.values())
