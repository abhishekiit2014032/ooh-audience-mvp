# OOH Audience Intelligence: MVP

A Python pipeline and Streamlit dashboard that estimates **visible impressions, unique monthly audience,
audience profile, duplication and planned-versus-actual delivery** for four outdoor hoardings in Dubai:
the main case on Sheikh Zayed Road (H1, near Financial Centre Metro) and three alternatives (H2 Umm Al
Sheif, H3 Dubai Marina, H4 Al Khail Road).

It answers Option B of the Radix brief *Making Outdoor Advertising Measurable & Actionable*. It
follows the method in the solution design doc *OOH Audience Intelligence: Solution Design and MVP Build
Guide*. **It runs end to end with no API keys**, and every number carries a label saying how far to trust it.

**Public URL:** _not deployed yet. See [Deploy](#deploy); paste the Streamlit Community Cloud URL here._

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
   traffic timing and a Dubai Statistics Center check. Relevant reach = unique × car-interest share.
8. **Duplication.** Shared segments are counted once. Otherwise a corridor rule applies: τ = 0.5 for
   faces on the same corridor and direction within 15 km, else 0.1. A greedy plan builder maximises
   incremental relevant reach per AED within the budget.
9. **Planned vs actual.** Plan = baseline advertiser impressions. Actual = campaign traffic × actual / planned
   plays from the play log. Delivery index = actual / planned, per week.
10. **Area news (context only).** Google News RSS and GDELT headlines for the corridor and the area,
    last 30 days, cached daily. Each headline is classified as traffic risk, audience boost, category
    relevance or other. Claude does the classifying when a key is set; keyword rules otherwise. Traffic-risk
    headlines flag a delivery risk. News never changes the reach numbers. Google News RSS suits a demo; a
    commercial product needs a licensed news API.
11. **Activation.** Exports the exposure zones as GeoJSON plus a centre and radius CSV for a data partner
    or platform. Nothing is executed.

### Results snapshot (default assumptions, no API keys, OSM cached 2026-10-31)

| Placement | Impressions / day | Unique / month (low – high) | Car-relevant / month | Label |
| --- | --- | --- | --- | --- |
| H1 Sheikh Zayed Road, DIFC | 111,600 | 418,600 (184,600 – 939,800) | 125,600 | SAMPLE (metro ridership) |
| H2 Sheikh Zayed Road, Umm Al Sheif | 75,100 | 281,800 (123,800 – 634,000) | 84,500 | SAMPLE (metro ridership) |
| H3 Sheikh Zayed Road, Dubai Marina | 107,300 | 402,200 (176,700 – 904,900) | 120,700 | SAMPLE (metro ridership) |
| H4 Al Khail Road, Al Quoz | 84,000 | 315,200 (136,600 – 714,400) | 94,600 | ESTIMATE |

H1's main carriageway reproduces the doc's worked example: 6 lanes, 115,200 vehicles a day and mean
visibility 0.515 give 88,900 impressions a day, against the doc's illustrative 86,400 at 0.5. Collector
roads, slip roads and the metro add the rest. Monthly frequency is the assumption that moves unique reach
most (Sensitivity page). With a budget of AED 400,000, the plan builder picks H4, H3 and H2.

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

| Page | What it shows |
| --- | --- |
| Map | Dark basemap, pins, exposure cones, visible segments coloured by V, tooltip with factor breakdown |
| Placement detail | The planner's five questions, reach funnel (low/base/high), hourly impressions, persona card |
| Compare locations | H1 to H4: daily impressions, unique monthly, relevant reach, AED per 1,000 relevant impressions |
| Duplication and plan | Overlap heatmap, overlap rules, greedy plan, combined vs naive reach |
| Planned vs actual | Weekly planned vs actual and the delivery index (SAMPLE) |
| Sensitivity | Tornado chart: which assumption moves unique reach most |
| Activation | GeoJSON and CSV downloads, partner routes, privacy limits |
| Area news | Latest 30 days of headlines for the corridor and area, sorted into traffic risk / audience boost / category relevance |
| Assumptions and sources | Every parameter with label and source, data sources, snapping log, known limits |

The sidebar has a slider for every scalar assumption in `config/assumptions.yaml`. The seven key ones are
on top; the rest are under "All other assumptions". It also has an editable road-class table, a placement
picker and a reset button. Geometry is cached once, so a slider change only re-runs the arithmetic.

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
| `config/placements.yaml` | Real face size, facing, height and rate card | — |

## Repository layout

```
config/            placements.yaml, assumptions.yaml
data/inputs/       SAMPLE inputs (flagged is_sample)
data/cache/        OSM GeoPackages (committed), API response cache (ignored)
data/outputs/      results.json, segments_H*.geojson, zones.geojson, zones_radius.csv, snap_log.json
src/ooh/           config, geometry, roads, traffic, visibility, reach, duplication, profile,
                   narrative, delivery, activation, metrics, pipeline
app/               streamlit_app.py
scripts/           fetch_osm.py
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
