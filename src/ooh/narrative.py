"""Placement persona and rationale: Claude API when a key is set, else a template.

The LLM only rewrites numbers the pipeline computed. The prompt passes them as JSON and
forbids new figures. Responses are cached by input hash, so the same placement and
assumptions never trigger a second call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from .config import CACHE_DIR, env_key
from .metrics import fmt_num

log = logging.getLogger(__name__)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")

SYSTEM = (
    "You write short audience notes for out-of-home media planners in Dubai. "
    "Use only the numbers in the JSON you are given, rounded as they appear; never invent "
    "new figures, sources or individuals. Keep the labels (ESTIMATE, ASSUMPTION, SAMPLE) next "
    "to the numbers they qualify. Plain English, no marketing language, no headings."
)

PROMPT = """Placement facts (JSON):
{facts}

Write two parts, separated by a blank line:
1. Persona: one or two sentences on who this placement mostly reaches (age, commute pattern, place context).
2. Why it fits the brief ({brand}): two or three sentences citing the unique audience, the car-relevant reach and one place signal, with their labels."""


def facts_for(placement, reach_metrics: dict, profile) -> dict:
    """The compact, citeable input for the narrative."""
    m = reach_metrics
    return {
        "placement": f"{placement.id} {placement.name}",
        "area": placement.area,
        "face": f"{placement.type}, {placement.width_m:g} x {placement.height_m:g} m",
        "daily_impressions": f"{fmt_num(m['impressions_day'].value)} ({m['impressions_day'].label})",
        "unique_monthly_audience": (f"{fmt_num(m['unique_month'].value)} "
                                    f"(range {fmt_num(m['unique_month'].low)} to "
                                    f"{fmt_num(m['unique_month'].high)}, {m['unique_month'].label})"),
        "car_relevant_reach": f"{fmt_num(profile.relevant_reach.value)} ({profile.relevant_reach.label})",
        "car_interest_share": f"{profile.interest_share.value:.0%} ({profile.interest_share.label})",
        "commuter_share_of_traffic": f"{profile.commuter_share:.0%} (ASSUMPTION, default commuter curve)",
        "points_of_interest_1km": profile.poi_counts,
        "segments": profile.segments,
        "meta_values_are_sample": profile.meta_is_sample,
    }


def template_narrative(facts: dict) -> str:
    pois = facts["points_of_interest_1km"]
    top = sorted(pois.items(), key=lambda kv: kv[1], reverse=True)[:2]
    places = " and ".join(f"{k.lower()} ({v})" for k, v in top if v) or "few mapped points of interest"
    age = facts["segments"]["Demographic"][0]
    commuter = facts["commuter_share_of_traffic"].split(" ", 1)[0]
    persona = (f"Mostly working-age drivers passing {facts['area']}. {age}"
               f"{' (SAMPLE Meta values)' if facts['meta_values_are_sample'] else ''}. "
               f"{commuter} of daily traffic falls in the weekday commuter peaks (ASSUMPTION, default "
               f"curve). Within 1 km the mapped places are mostly {places}.")
    why = (f"{facts['placement']} reaches an estimated {facts['unique_monthly_audience']} unique people "
           f"a month. At a car-interest share of {facts['car_interest_share']} that is about "
           f"{facts['car_relevant_reach']} car-relevant people. "
           f"{facts['segments']['Behavioural'][2]}.")
    return f"{persona}\n\n{why}"


def _cache_path(key: str):
    return CACHE_DIR / "api" / "narrative" / f"{hashlib.sha1(key.encode()).hexdigest()}.json"


def claude_narrative(facts: dict, brand: str) -> str | None:
    """Ask Claude for the narrative. Returns None without a key, on error or on refusal."""
    if not env_key("ANTHROPIC_API_KEY"):
        return None
    payload = json.dumps(facts, sort_keys=True)
    path = _cache_path(MODEL + payload + brand)
    if path.exists():
        return json.loads(path.read_text())["text"]
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": PROMPT.format(facts=payload, brand=brand)}],
        )
    except Exception as exc:  # any API, network or SDK error falls back to the template
        log.warning("Claude narrative failed, using template: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": MODEL, "text": text}))
    return text


def narrative(facts: dict, brand: str, use_llm: bool = True) -> tuple[str, str]:
    """Return (text, source)."""
    if use_llm:
        text = claude_narrative(facts, brand)
        if text:
            return text, f"Claude API ({MODEL}), from computed numbers only"
    return template_narrative(facts), "Template filled with computed numbers"
