# OOH Audience Intelligence: MVP

A Python pipeline and Streamlit dashboard that estimates **visible impressions, unique monthly audience,
audience profile, duplication and planned-versus-actual delivery** for four outdoor hoardings in Dubai:
the main case on Sheikh Zayed Road (H1, near Financial Centre Metro) and three alternatives (H2 Umm Al
Sheif, H3 Dubai Marina, H4 Al Khail Road).

It answers Option B of the Radix brief *Making Outdoor Advertising Measurable & Actionable*. It
follows the method in the solution design doc *OOH Audience Intelligence: Solution Design and MVP Build
Guide*. **It runs end to end with no API keys**, and every number carries a label saying how far to trust it.

**Public URL:** _not deployed yet. See [Deploy](#deploy); paste the Streamlit Community Cloud URL here._



## ▶ Watch the xplainer

0:00 The problem and the solution · 3:29 From idea to implementation · 6:49 Sheikh Zayed Road use case



https://github.com/user-attachments/assets/6cb65454-b47a-4af0-ad83-c000f68ad1b2




https://github.com/user-attachments/assets/f7fd8d8c-85d7-47c3-9291-941c0bfea8d2


## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

Command-line run (writes `data/outputs/`):

```bash
PYTHONPATH=src python -m ooh.pipeline
```

Tests:

```bash
pytest
```

OpenStreetMap data for the four placements is cached in `data/cache/osm_H*.gpkg` and committed, so the app
starts offline. To refresh it from Overpass:

```bash
python scripts/fetch_osm.py --force
```

## Labels

| Label | Meaning | Example |
| --- | --- | --- |
| VERIFIED | Published by an official or named source | RTA: up to 14,000 vehicles/hour on 7 lanes (2,000 per lane) |
| ESTIMATE | Calculated from verified data plus a stated assumption | Daily vehicles facing the hoarding |
| ASSUMPTION | A parameter we chose, editable in the sidebar | 1.5 people per vehicle; 8 passes per person per month |
| SAMPLE | Placeholder input, not real data | Meta reach values, metro ridership, play log |
| CONCEPT | Needs a partner or further validation | Re-targeting exposed devices |

A number takes the weakest label of its inputs. With the shipped SAMPLE inputs, the traffic-based reach
numbers are ESTIMATES, and anything that uses metro ridership or Meta values is SAMPLE.

## How it works

1. **Snap.** Each configured coordinate snaps to the nearest carriageway on OSM that matches the corridor
   name or ref and whose traffic flows towards the face. The face is placed 15 m to the right of that
   carriageway and turned to face oncoming traffic. The result is logged in `data/outputs/snap_log.json`
   and on the Assumptions page.
2. **Exposure cone.** A circular sector: radius 400 m, half-angle 35°, centred on the facing bearing.
3. **Directed segments.** OSM drivable roads are cut into ~25 m segments. A segment counts if its midpoint
   is in the cone and its travel direction points towards the face (≤ 60°).
4. **Visibility** `V = D × A × O × S × T × SOV` per segment: distance, angle, 2D line of sight against
   OSM buildings, face size, dwell and share of voice.
5. **Volume.** TomTom Traffic Volume is the first choice, if a contract confirms UAE coverage. Otherwise the
   RTA-capacity fallback is used: `lanes × 2,000 × utilisation × 24`. That total is shaped by an hourly
   commuter curve, and each hour is capped at lane capacity.
6. **Reach.** `I_day = Σ_flows Vol × occupancy × mean V (+ metro riders × window factor × V_metro)`.
   Then `Unique_month = I_day × 30 / f`. Low, base and high scenarios move together:
   - low: low utilisation and occupancy, f = 12
   - high: high utilisation and occupancy, f = 5
7. **Profile.** Combines Meta reach estimate (age, gender, interest), OSM points of interest within 1 km,
   traffic timing and a Dubai Statistics Center check. Relevant reach = unique × the campaign's interest share, tilted by local fit (below).
8. **Duplication.** Shared segments are counted once. Otherwise a corridor rule applies: τ = 0.5 for
   faces on the same corridor and direction within 15 km, else 0.1. The plan builder tries every mix of
   the brief's number of boards (`boards:` per campaign) and keeps the one that reaches the most relevant
   people. No prices are used anywhere (see "No money" below).
9. **Planned vs actual.** Plan = baseline advertiser impressions. Actual = campaign traffic × actual / planned
   plays from the play log. Delivery index = actual / planned, per week.
10. **Online signals → dated events → forecast.** Recent headlines are collected per corridor and area
    from Google News and GDELT, and stored once in `data/signals/ledger.json`. The flow:
    - **Extract:** Claude reads each new article once and returns the event type, date, hours, corridor or
      area, and confidence. The extraction is then frozen.
    - **Look up:** for events missing a date, hours or road section, Claude's web search finds them, with
      cited links.
    - **Filter:** off-location, undated and out-of-window articles are kept but marked rejected or pending,
      with a reason, so the noise filter can be audited.
    - **De-duplicate:** articles collapse into one event per (type, corridor or area, date).
    - **Apply:** switched-on events adjust a separate news-adjusted campaign forecast. The typical month
      stays unchanged, so faces remain comparable. Effect sizes are ASSUMPTIONS in config (Events group);
      the AI never sets them.

    Refresh with the button under Check the data → Road events or `python scripts/refresh_signals.py`. Planners
    can add known closures in `data/inputs/events.yaml`.

    **People numbers from the news** (`src/ooh/footprint.py`). News is also a data source for how many
    people are at each location: event attendance, visitors to malls and attractions, new homes and
    offices, metro riders and traffic counts.
    - **Search:** one Claude web-search call per location (its `nearby_places` in `placements.yaml`)
      plus one Dubai-wide search per campaign industry (car events, property shows and new homes, shopping
      festivals and mall crowds), with recent headlines as leads. City-wide totals (e.g. Dubai Shopping
      Festival attendance) stay Dubai-wide context and are never pinned to one board.
    - **Validate:** a number is kept only when its quote states it (35,000 / 35k / 35 thousand) and its
      link is a page the search really returned. Venue capacities are marked and never modelled.
    - **Group:** the same thing on the same date from several sources becomes one number with a range.
    - **Per campaign:** facts are stored without a campaign. Each campaign takes the dated crowds inside
      its window and turns them into extra people passing a nearby board with config ASSUMPTIONS
      (`news_event_pass_share`, `news_audience_match_share` for crowds that match the campaign's
      `news_tags`, capped by `event_max_daily_change`). Visitor, resident and ridership numbers are
      evidence only. The plan is re-run with the crowds added to show whether the pick would change.

    Refresh with the button under Check the data → Web-sourced numbers or `python scripts/refresh_people.py`. Facts go to
    `data/signals/people.json`; planners can add their own in `data/inputs/people_facts.yaml`.
11. **Activation.** Exports the exposure zones as GeoJSON plus a centre and radius CSV for a data partner
    or platform. Nothing is executed.

### Results snapshot (default assumptions, no API keys, OSM cached 2026-10-31)

| Placement | Impressions / day | Unique / month (low – high) | SUV-launch audience / month | Label |
| --- | --- | --- | --- | --- |
| H1 Sheikh Zayed Road, DIFC | 111,600 | 418,600 (184,600 – 939,800) | 125,600 | SAMPLE (metro ridership) |
| H2 Sheikh Zayed Road, Umm Al Sheif | 75,100 | 281,800 (123,800 – 634,000) | 84,500 | SAMPLE (metro ridership) |
| H3 Sheikh Zayed Road, Dubai Marina | 107,300 | 402,200 (176,700 – 904,900) | 120,700 | SAMPLE (metro ridership) |
| H4 Al Khail Road, Al Quoz | 84,000 | 315,200 (136,600 – 714,400) | 94,600 | ASSUMPTION (interest share) |

H1's main carriageway reproduces the doc's worked example: 6 lanes, 115,200 vehicles a day and mean
visibility 0.515 give 88,900 impressions a day, against the doc's illustrative 86,400 at 0.5. Collector
roads, slip roads and the metro add the rest. Monthly frequency is the assumption that moves unique reach
most (Stress-test the pick page). The impressions, unique and campaign-audience figures per board are the ones in
the AI Solution Brief response; `tests/test_knowledge.py` fails if the engine stops reproducing them. The brief's
plan differs on purpose: it was chosen by price (H4, H3 and H2 for AED 280,000, 273,000 car & SUV fans). With no
prices, the SUV brief books 3 boards and the best 3 are H1, H3 and H4 (DIFC, Dubai Marina, Al Quoz), reaching
about 310,000 car & SUV fans with shared people counted once. The property and retail briefs book 2 boards each;
both pick DIFC and Dubai Marina.

**No money.** The app holds no prices, budgets or currency. Where a number would rest only on our own assumption it
is shown as a 1–4 rating (●○○○ Low to ●●●● Very high), labelled Assumption:
- **Price level** per board (`price_level:` in `config/placements.yaml`, 1 = cheapest of our boards).
- **Value**: campaign audience per price level, relative to the best board.
- **Rush-hour traffic** (from a standard commuter curve, not counts), **income** (from the district) and each
  campaign's **audience share of passers-by**.
- The solution options in `config/brief.yaml` show the **data needed** (●○○ to ●●●) instead of a cost.

Numbers from data (traffic, reach, audience profile, places, delivery) stay as figures with their ranges and labels.
`tests/test_app.py::test_no_money_on_any_page` fails if AED, USD, a budget or a "cost per" appears on any page.

**Coordinate corrections.** The doc's coordinates are marked approximate, and two were off:
- **H2:** 25.1440, 55.2120 sits on Al Wasl Road, 750 m from Sheikh Zayed Road. Moved to 25.1407, 55.2184.
- **H4:** 25.1700, 55.2520 is 1.7 km west of Al Khail Road. Moved to 25.1694, 55.2690.

Both are noted in `config/placements.yaml`.

### Deviations from the build guide, and why

- **Dwell T** uses the viewing time of the whole visible approach on a flow (visible length / speed), not
  one 25 m piece. Per-piece time would make T depend on how finely the road is cut: 25 m at 80 km/h is
  1.1 s, which would cap every highway at T ≈ 0.4.
- **Impressions are summed per flow**, not per segment. A flow is one road, class and direction. Each vehicle
  is one potential impression weighted by mean V along its approach; summing 16 segments of the same
  carriageway would count every car 16 times. This matches the doc's worked example (volume × average
  visibility).
- **Road-class utilisation factor** (ASSUMPTION, editable). The doc's 0.40 utilisation is applied in full to
  motorways and trunk roads and scaled down for smaller roads. Without it, a residential street inside the
  cone would carry 19,200 vehicles a day.
- **Hourly cap.** Every hour is clipped at `lanes × 2,000`, and the number of clipped hours is reported. This
  keeps the high case physically possible.

## Pages

The app has two parts, picked with the switch at the top of the sidebar; each part lists only its own pages.

**📊 Insights** opens first: five pages in the order of the AI Solution Brief. Each page shows a heading and its
numbers; the ⓘ on a number opens Data sources on that number's source.

| Insights page | What it shows |
| --- | --- |
| 1 · Locations | Close-up map of the selected board (default DIFC on Sheikh Zayed Road) with its viewing wedge and the roads that see it, next to its numbers (each with an ⓘ to its source): vehicles, people and impressions a day, unique people a month (low–high), campaign audience and the price-level rating. Below: every board on one map and a card per location |
| 2 · Data sources | In three numbered sections: ① how the data flows (diagram), ② how far to trust each source (confidence table), ③ every number for the selected location (about 50), grouped (traffic, visibility, reach, audience, nearby, board, delivery, news) with its value, label, source and confidence; tick a row for how it is made and the exact figure or quote taken. Arriving from an ⓘ shows that number's source at the top |
| 3 · Audience profile | Gender, age, interests, how and when people pass, what is nearby and income and crowds for one location; every block has a "How we know" drill-down to its sources |
| 4 · Compare locations | Two locations side by side: two mini maps, where each one wins, a row-by-row table by sector (traffic, visibility, reach, audience, nearby, board and ratings) with the better value in green and the people who pass both, a drill-down into any row for both locations, and the best plan with a number-of-boards slider |
| 5 · Campaign performance | The standard outdoor metrics for the whole campaign or one board: delivery (views delivered vs planned, delivery index, plays delivered, share of voice), reach (reach, frequency, GRPs, campaign audience), efficiency as ratings (price level, value, audience fit, bookings per 10k) and response (QR scans, visits, bookings, lift), weekly planned vs delivered, the funnel and the three re-engagement routes. Sample data until live feeds connect |

**🧭 Plan a campaign** holds the planning tools in two groups:

- **Plan**: The brief (the AI Solution Brief answered by the live engine), Overview, Explore a location, Score &
  compare, Decision, Duplication and plan, Campaign health.
- **Check and hand off**: Map, Placement detail, Check the data, Stress-test the pick, Hand off, Assumptions and
  sources.

A button that opens a page in the other part (for example Explore's "Decision →") switches the part too. The
campaign and location pickers sit in a small button at the top right of every page and stay closed until opened:

- **Campaign** (`campaigns:` in `config/placements.yaml`): dates, number of boards and target audience. The target audience is
  everyone passing × the campaign's interest share (an ASSUMPTION until Meta values are entered; then the Meta interest
  in `meta_interest` is used). Three example campaigns from three industries ship, so the same boards are judged
  three ways: 🚙 **SUV launch** (cars, Nov 2026), 🏙️ **Off-plan apartment launch** (property, Dec 2026) and
  🛍️ **Winter shopping festival** (retail, Jan 2027).
- **Location in focus**: set here, by clicking a pin on the Overview map, or with a location card's "Explore" button.

Pages call locations by name (`short_name`) and split "everyone who passes" from the campaign audience.

### Knowledge layer

Every data source files **facts** into one campaign-free knowledge layer (`src/ooh/knowledge.py`): a number or
statement about a location (or all of Dubai) with its sources, trust label, topic, tags and the outcomes it feeds.
About 155 facts come from 12 sources today. When a campaign is picked, a readable relevance rule
(`config/knowledge.yaml`) keeps only what matters for it:

`relevance = topic base + tag match (campaign audience) + inside campaign window − weak figure`; core numbers are
always used, another campaign's brief and other audiences' interests are dropped, and a fact is used at 0.6 or more.
Each industry reads a different slice: the SUV launch uses about 77 facts (traffic, drivers, car showrooms, car
events), the property launch about 59 (premium and business districts, new homes, population growth) and the
retail festival about 42 (malls, food and leisure, shopping crowds).

Locations are scored 0–100 on five criteria from those facts, weighted per campaign (weights movable on the page):
campaign audience, value (audience per price-level rating; both relative to the best board), audience fit (local signals per campaign, e.g.
car showrooms and drivers for the SUV launch; premium area, offices and commuters for the property launch; malls,
food and leisure and hotels for the retail festival), crowd timing
(sourced crowds in the window; 5% extra audience = 100) and data confidence (trust of the facts used).

The registry's "feeds" for each source are checked against the facts in `tests/test_knowledge.py`, so the diagram
only shows links the facts back up.

**Fit also moves the plan.** Until real Meta interest shares per board arrive, every board would get the same share
of a campaign's audience, so the plan builder could not tell a car launch from a property launch. `fit_tilt`
(ASSUMPTION, set per campaign in `config/placements.yaml`, slider under Analyst controls) scales each board's share
by its local fit, keeping the average share as configured: `factor = (1 − t) + t × fit / mean fit`. The SUV launch
keeps 0 (one flat share at every board, as in the solution brief's worked example); the property launch and the
retail festival use 0.5. The plans then differ by industry: the SUV launch buys Al Quoz, Dubai Marina and Umm Al
Sheif; the property launch buys Dubai Marina and DIFC; the retail festival buys Dubai Marina and Al Quoz. With a
tilt above 0, fit counts twice on the Score page (inside campaign audience and as its own criterion); the page
says so.

| Executive page | The decision it supports |
| --- | --- |
| The brief | The AI Solution Brief, answered live for its worked example (SUV launch, November, 3 boards): the answer in one line, the planner's questions from Section 4 each with a "Show me" button to the page that proves it, the H1–H4 comparison, the four labels; what is real today (capability status, data confidence today → once connected, what the AI does); and the path to market (roadmap, options with the data each needs, risks, value from `config/brief.yaml`, marked "plan, not computed") |
| Overview | The map first: every board with its viewing wedge, the roads that see it and its rank for the campaign; click a pin or a card to explore it. Below it, the knowledge-layer flow: sources → facts by topic → outcomes, with particles on the facts the chosen campaign uses (switch campaigns in place) |
| Explore a location | One board through the chosen campaign's eyes: ID card with rank, engagement (people and campaign audience a month, seconds in view, visibility, rush share, metro riders), the funnel "N facts known → M matter", fact cards by topic with relevance, trust and source links; then "Who passes" or "Crowds & news" |
| Score & compare | Ranking on the five criteria with live weight sliders and reasons per criterion, why a board is or is not in the plan (overlap with plan boards, number of boards, value), and every campaign × location score at a glance |
| Decision | Which billboards to book: the best mix for the brief's number of boards, de-duplicated campaign-audience reach, what one more board would add, and why the left-out board did not make it. Toggle billboards or move the number-of-boards slider to try other mixes instantly |
| Campaign health | Delivered vs planned views per billboard, status, weekly trend, and road events that change the forecast |

| Analyst page | What it shows |
| --- | --- |
| Data sources | The data-flow diagram (sources → knowledge layer → outcomes, counted from the facts) plus the confidence table: status, score, facts filed and the outcomes each source feeds |
| Map | Light basemap, pins, exposure cones, visible segments coloured by V, tooltip with factor breakdown |
| Check the data | Is the pick built on solid facts? Facts used vs total, measured vs placeholder, and what you switched off. Tabs: **Weakest links** (placeholder facts grouped by the source that limits them, most core numbers first, each with how to fix it), **All facts** (every fact with relevance, why it is or is not used, trust, sources, outputs it feeds and how to improve it), **Web-sourced numbers** and **Road events** (on/off switches that change scores, crowds and forecast at once), **Sources** (confidence table) |
| Stress-test the pick | Would we book different boards if an assumption is wrong? Every assumption at its low and high end one at a time; the plan is rebuilt each time. Lists each flip with its tipping point, charts how far the pick's campaign audience moves, full table in an expander |
| Hand off | Book it, target it, track it: booking sheet for the plan's boards (CSV), viewing-zone files for mobile retargeting for those boards only (GeoJSON, centre + radius CSV), routes, measurement and privacy limits, and a link to Campaign health |
| Assumptions and sources | Every parameter with label and source, data sources, snapping log, known limits |

The sidebar's **Analyst controls** have a slider for every scalar assumption in `config/assumptions.yaml`. The seven
key ones are under "Key assumptions"; the rest are under "All other assumptions". It also has an editable
road-class table, a reset button and, on the pages that need it, a billboard picker. Geometry is cached once, so a slider change only re-runs the arithmetic.

## Confidence score per data source

`src/ooh/sources.py` is the one registry of sources. The Data sources page, its diagram and the Assumptions
page all read from it. Each source gets a 0–100 confidence score:

`score = 100 × status × (0.40 provenance + 0.35 directness + 0.25 freshness)`

- **status:** live, cached or configured 1; SAMPLE 0.35; not connected 0.
- **Potential** is the same score once a source is connected and live.
- Status is read locally: API keys present, cache dates and `is_sample` flags. The page makes no network calls.

The score is a planning heuristic (ASSUMPTION). It is separate from the labels on individual numbers and
never enters the reach maths. In the diagram, the geospatial model does the counting. Claude explains the
numbers and turns news into dated events, which the model applies with effect sizes from config.

## API keys (all optional)

Copy `.env.example` to `.env` (or set them as Streamlit secrets / environment variables).

| Key | Used for | Without it |
| --- | --- | --- |
| `TOMTOM_API_KEY` | Traffic Flow speeds for dwell | OSM maxspeed × 0.8. Traffic Volume is not called: it is contract-based and UAE coverage is unconfirmed |
| `DUBAI_PULSE_KEY` / `_SECRET` | RTA metro ridership API | `data/inputs/metro_ridership.csv` (SAMPLE) |
| `MAPILLARY_TOKEN` | Street-imagery line-of-sight check (Phase 2) | 2D building footprints |
| `ANTHROPIC_API_KEY` | Claude writes persona narratives from the computed numbers only, and classifies and summarises area news from the fetched headlines only | Template narrative; keyword rules for news |

## Replacing SAMPLE inputs

| File | Replace with | Then |
| --- | --- | --- |
| `data/inputs/meta_reach.json` | Meta Ads Manager reach estimates (pin on the face, 1 km, UAE) | set `"is_sample": false` |
| `data/inputs/metro_ridership.csv` | Dubai Pulse `rta_metro_ridership-open`, daily riders per station | set `is_sample` to `false` per row |
| `data/inputs/dsc_population.json` | Dubai Statistics Center population by area, age, gender | set `"is_sample": false` |
| `data/inputs/play_log.csv` | The media owner's play log for the digital faces | set `is_sample` to `false` per row |
| `config/placements.yaml` | Real face size, facing and height; a price level from the media owner's quotes | — |

## Repository layout

```
config/            placements.yaml, assumptions.yaml, knowledge.yaml
data/inputs/       SAMPLE inputs (flagged is_sample)
data/cache/        OSM GeoPackages (committed), API response cache (ignored)
data/outputs/      results.json, segments_H*.geojson, zones.geojson, zones_radius.csv, snap_log.json
src/ooh/           config, geometry, roads, traffic, visibility, reach, duplication, profile,
                   narrative, delivery, activation, metrics, pipeline, footprint (people numbers),
                   knowledge (facts, relevance, scoring), exec_ui / flow_viz (page widgets)
app/               streamlit_app.py
scripts/           fetch_osm.py, refresh_signals.py (road events), refresh_people.py (people numbers)
tests/             pytest suite, including a Streamlit AppTest smoke test of every page
```

## Deploy

**Streamlit Community Cloud (free).**
1. Push this folder to a GitHub repository (it is the repo root, so `requirements.txt` sits at the top).
2. On share.streamlit.io choose *New app* → the repo → main file `app/streamlit_app.py` → Python 3.11.
3. Optionally add keys under *Advanced settings → Secrets*, e.g. `ANTHROPIC_API_KEY = "..."`.
4. Paste the app URL at the top of this README.

**Any container host.**

```bash
docker build -t ooh-mvp .
docker run -p 8501:8501 --env-file .env ooh-mvp
```

## Known limits

- **Frequency and duplication are assumptions.** Unique reach can be off by 2x or more until Phase 2 mobile
  data calibrates them. Always read the range.
- **No public Sheikh Zayed Road daily count exists.** Volume is the RTA-capacity estimate times a
  utilisation assumption.
- **Slip roads and collector roads are separate flows.** A vehicle that uses both inside one cone can be
  counted twice.
- **Line of sight is 2D.** Bridges, trees and other boards are missed.
- **Metro riders use the nearest station's ridership,** not the line load past the face.
- **Hoarding coordinates in the doc are approximate.** Snapping picks the nearest matching carriageway;
  check the snapping log against the real site.
- **Activation is a concept.** The exports are inputs for a partner, not a campaign.
