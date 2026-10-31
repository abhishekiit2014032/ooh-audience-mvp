"""Latest news around each placement: context and delivery-risk signals, never reach inputs.

Sources (no key needed):

* Google News RSS search, region AE, last 30 days.
* GDELT DOC 2.0 API (rate limit: one request per 5 seconds).

Results are cached per placement per day under data/cache/api/news/. Each headline is
classified into a signal type. With ANTHROPIC_API_KEY set, Claude classifies the headlines and
writes a short note per placement, citing only the fetched articles; otherwise keyword rules
classify and a template writes the note.

Google News RSS suits a demo. A commercial product needs a licensed news API.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from .config import CACHE_DIR, Placement, env_key

log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "ooh-audience-mvp/0.1 (research demo)"
LOOKBACK_DAYS = 30
MAX_ITEMS = 25

SIGNALS = {
    "traffic_risk": "Traffic risk",
    "audience_boost": "Audience boost",
    "category": "Category relevance",
    "other": "Other",
}

# Keyword rules used when no Claude key is set (ASSUMPTION; deliberately simple).
KEYWORDS = {
    "traffic_risk": ["road work", "roadwork", "closure", "closed", "diversion", "detour", "traffic",
                     "congestion", "accident", "crash", "interchange", "rta ", "takes over", "dubai ride",
                     "dubai run", "marathon", "road block", "maintenance work", "salik"],
    "category": ["car", "suv", "motor", "automotive", "showroom", "dealership", "vehicle", "ev ", "electric vehicle",
                 "toyota", "nissan", "lexus", "bmw", "mercedes", "tesla", "porsche", "hyundai", "kia"],
    "audience_boost": ["festival", "event", "exhibition", "expo ", "concert", "mall", "hotel opening",
                       "tourist", "visitors", "new year", "gitex", "dubai fitness", "shopping", "season",
                       "summit", "week ", "fair", "show "],
}

# Query terms per placement: the corridor and the area words, as people write them in news.
AREA_TERMS = {
    "H1": ['"Sheikh Zayed Road"', '"DIFC" OR "Downtown Dubai" OR "Financial Centre"'],
    "H2": ['"Sheikh Zayed Road"', '"Umm Al Sheif" OR "Al Barsha" OR "Mall of the Emirates"'],
    "H3": ['"Sheikh Zayed Road"', '"Dubai Marina" OR "JLT" OR "Jumeirah Lakes Towers"'],
    "H4": ['"Al Khail Road"', '"Al Quoz" OR "Al Khail"'],
}


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published: str          # ISO date
    feed: str               # "Google News" or "GDELT"
    signal: str = "other"
    reason: str = ""
    classified_by: str = "keyword rules"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AreaNews:
    placement_id: str
    items: list[NewsItem]
    summary: str
    summary_source: str
    fetched_on: str
    errors: list[str]

    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in SIGNALS}
        for it in self.items:
            out[it.signal] = out.get(it.signal, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {"placement_id": self.placement_id, "items": [i.to_dict() for i in self.items],
                "summary": self.summary, "summary_source": self.summary_source,
                "fetched_on": self.fetched_on, "errors": self.errors, "counts": self.counts()}


# --------------------------------------------------------------------------- fetch


def _cache_file(name: str):
    return CACHE_DIR / "api" / "news" / name


def _queries(placement: Placement) -> list[str]:
    terms = AREA_TERMS.get(placement.id, [f'"{placement.corridor}"', f'"{placement.area}"'])
    corridor, area = terms
    return [f"{corridor} Dubai", f"({area}) Dubai"]


def _google_news(query: str) -> list[NewsItem]:
    resp = requests.get(GOOGLE_NEWS_RSS, params={"q": f"{query} when:{LOOKBACK_DAYS}d", "hl": "en-AE", "gl": "AE",
                                                 "ceid": "AE:en"},
                        headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    items = []
    for it in ET.fromstring(resp.content).findall(".//item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except (TypeError, ValueError):
            published = ""
        items.append(NewsItem(title, source, it.findtext("link") or "", published, "Google News"))
    return items


def _gdelt(query: str) -> list[NewsItem]:
    resp = requests.get(GDELT_DOC, params={"query": f"{query} sourcelang:english", "mode": "artlist",
                                           "format": "json", "maxrecords": 25, "timespan": f"{LOOKBACK_DAYS}d",
                                           "sort": "datedesc"},
                        headers={"User-Agent": USER_AGENT}, timeout=40)
    resp.raise_for_status()
    try:
        arts = resp.json().get("articles", [])
    except ValueError:  # GDELT answers rate limits and bad queries in plain text
        raise RuntimeError(resp.text[:120])
    items = []
    for a in arts:
        seen = a.get("seendate", "")
        published = f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}" if len(seen) >= 8 else ""
        items.append(NewsItem(a.get("title", "").strip(), a.get("domain", ""), a.get("url", ""), published, "GDELT"))
    return items


_GDELT_BLOCKED = False  # set after a rate-limit answer; skips GDELT for the rest of the process


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower())[:80]


def fetch_news(placement: Placement, use_gdelt: bool = True) -> tuple[list[NewsItem], list[str]]:
    """Fetch and de-duplicate headlines for a placement. Cached once per day."""
    today = date.today().isoformat()
    path = _cache_file(f"{placement.id}_{today}.json")
    if path.exists():
        data = json.loads(path.read_text())
        return [NewsItem(**i) for i in data["items"]], data["errors"]

    global _GDELT_BLOCKED
    items: list[NewsItem] = []
    errors: list[str] = []
    for q in _queries(placement):
        try:
            items += _google_news(q)
        except Exception as exc:  # network, parsing
            errors.append(f"Google News: {exc}")
        if use_gdelt and not _GDELT_BLOCKED:
            try:
                items += _gdelt(q)
            except Exception as exc:
                errors.append(f"GDELT: {str(exc)[:80]}")
                _GDELT_BLOCKED = "429" in str(exc) or "limit" in str(exc).lower()
            time.sleep(5.5)  # GDELT asks for one request every 5 seconds

    seen: set[str] = set()
    unique = []
    for it in sorted(items, key=lambda i: i.published, reverse=True):
        key = _norm_title(it.title)
        if it.title and key not in seen:
            seen.add(key)
            unique.append(it)
    unique = unique[:MAX_ITEMS]
    if unique:  # do not cache a total failure; try again next time
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"items": [i.to_dict() for i in unique], "errors": errors}))
    return unique, errors


# --------------------------------------------------------------------------- classify


def keyword_signal(title: str) -> tuple[str, str]:
    text = f" {title.lower()} "
    for signal in ("traffic_risk", "category", "audience_boost"):
        hits = [k for k in KEYWORDS[signal] if k in text]
        if hits:
            return signal, f"keyword: {hits[0].strip()}"
    return "other", ""


CLAUDE_SYSTEM = (
    "You sort local news headlines for an outdoor-advertising planner in Dubai. Use only the headlines given. "
    "Never add facts, numbers or events that are not in a headline. Answer with JSON only."
)

CLAUDE_PROMPT = """Placement: {placement} ({area}), on {corridor}. Campaign: {brand}.

Headlines (JSON list, index = id):
{headlines}

Return JSON: {{"items": [{{"id": <int>, "signal": "traffic_risk" | "audience_boost" | "category" | "other", "reason": "<= 12 words"}}], "summary": "<two sentences on what matters for this placement and campaign, citing headline ids like [3]>"}}

traffic_risk = road works, closures, diversions or congestion that could cut traffic past the face.
audience_boost = events, openings or developments that could bring more people past the face.
category = news about cars, SUVs, dealers or the auto market relevant to the campaign."""


def _claude_classify(placement: Placement, brand: str, items: list[NewsItem]) -> tuple[dict, str] | None:
    if not env_key("ANTHROPIC_API_KEY") or not items:
        return None
    headlines = json.dumps([f"{i.published} | {i.title} ({i.source})" for i in items], ensure_ascii=False)
    prompt = CLAUDE_PROMPT.format(placement=placement.name, area=placement.area, corridor=placement.corridor,
                                  brand=brand, headlines=headlines)
    from .narrative import MODEL

    key = hashlib.sha1((MODEL + prompt).encode()).hexdigest()
    path = _cache_file(f"claude_{key}.json")
    if path.exists():
        return json.loads(path.read_text()), MODEL
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=CLAUDE_SYSTEM,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # API, network or SDK error: fall back to keyword rules
        log.warning("Claude news classification failed: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    if not data or "items" not in data:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data, MODEL


def _template_summary(items: list[NewsItem]) -> str:
    risk = [i for i in items if i.signal == "traffic_risk"]
    boost = [i for i in items if i.signal == "audience_boost"]
    cat = [i for i in items if i.signal == "category"]
    parts = [f"{len(items)} headlines in the last {LOOKBACK_DAYS} days: {len(risk)} traffic risk, "
             f"{len(boost)} audience boost, {len(cat)} car-category."]
    if risk:
        parts.append(f"Check delivery against plan: \"{risk[0].title}\" ({risk[0].published}).")
    elif boost:
        parts.append(f"Possible audience lift: \"{boost[0].title}\" ({boost[0].published}).")
    return " ".join(parts)


def area_news(placement: Placement, brand: str, use_llm: bool = True, use_gdelt: bool = True) -> AreaNews:
    items, errors = fetch_news(placement, use_gdelt=use_gdelt)
    for it in items:
        it.signal, it.reason = keyword_signal(it.title)
    summary, summary_source = "", "Template from keyword rules"
    result = _claude_classify(placement, brand, items) if use_llm else None
    if result:
        data, model = result
        for row in data.get("items", []):
            idx = row.get("id")
            if isinstance(idx, int) and 0 <= idx < len(items) and row.get("signal") in SIGNALS:
                items[idx].signal = row["signal"]
                items[idx].reason = str(row.get("reason", ""))[:120]
                items[idx].classified_by = f"Claude ({model})"
        summary = str(data.get("summary", "")).strip()
        summary_source = f"Claude API ({model}), from the fetched headlines only"
    if not summary:
        summary = _template_summary(items) if items else "No headlines found for this area in the last 30 days."
    return AreaNews(placement.id, items, summary, summary_source,
                    datetime.now(timezone.utc).date().isoformat(), errors)
