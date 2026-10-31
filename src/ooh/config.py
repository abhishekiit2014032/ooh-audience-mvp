"""Load and validate the YAML configuration with pydantic.

Two files drive the model:

* ``config/placements.yaml``: the hoardings and the campaign.
* ``config/assumptions.yaml``: every parameter, with its label, source and range.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
INPUT_DIR = DATA_DIR / "inputs"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "outputs"

Label = Literal["VERIFIED", "ESTIMATE", "ASSUMPTION", "SAMPLE", "CONCEPT"]


class Placement(BaseModel):
    """One OOH face, as configured (before snapping to the road)."""

    id: str
    name: str
    area: str = ""
    lat: float
    lon: float
    corridor: str
    road_match: list[str] = Field(default_factory=list)
    facing_bearing_deg: float
    type: Literal["digital", "static"]
    width_m: float
    height_m: float
    loop_seconds: float = 1
    slot_seconds: float = 1
    cone_radius_m: float = 400
    cost_per_month_aed: float

    @property
    def face_area_m2(self) -> float:
        return self.width_m * self.height_m

    @property
    def share_of_voice(self) -> float:
        """Slot seconds / loop seconds for digital faces; 1 for static."""
        if self.type == "static":
            return 1.0
        return min(1.0, self.slot_seconds / self.loop_seconds)


class Campaign(BaseModel):
    brand: str
    brand_category: str
    plan_start: date
    plan_end: date
    budget_aed: float
    baseline_start: date
    baseline_end: date


class PlacementConfig(BaseModel):
    placements: list[Placement]
    campaign: Campaign

    @field_validator("placements")
    @classmethod
    def _unique_ids(cls, v: list[Placement]) -> list[Placement]:
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("placement ids must be unique")
        return v


class Parameter(BaseModel):
    """One model parameter. ``low`` / ``high`` feed the low and high scenarios."""

    value: float
    low: float | None = None
    high: float | None = None
    label: Label
    group: str
    unit: str = ""
    min: float
    max: float
    step: float
    description: str
    source: str
    source_url: str | None = None


class RoadClass(BaseModel):
    lanes: int
    utilisation_factor: float
    speed_kmh: float


class HourlyProfile(BaseModel):
    label: Label
    source: str
    shares: list[float]

    @field_validator("shares")
    @classmethod
    def _normalise(cls, v: list[float]) -> list[float]:
        if len(v) != 24:
            raise ValueError("hourly profile needs 24 values")
        total = sum(v)
        return [s / total for s in v]


class AssumptionConfig(BaseModel):
    parameters: dict[str, Parameter]
    road_classes: dict[str, RoadClass]
    hourly_profile: HourlyProfile

    def road_class(self, highway: str) -> RoadClass:
        return self.road_classes.get(highway, self.road_classes["default"])


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_placements(path: Path | None = None) -> PlacementConfig:
    return PlacementConfig.model_validate(_read_yaml(path or CONFIG_DIR / "placements.yaml"))


def load_assumptions(path: Path | None = None) -> AssumptionConfig:
    return AssumptionConfig.model_validate(_read_yaml(path or CONFIG_DIR / "assumptions.yaml"))


Scenario = Literal["low", "base", "high"]
SCENARIOS: tuple[Scenario, ...] = ("low", "base", "high")


class Params:
    """Resolved parameter values for one run, with optional overrides from the UI.

    A slider moves the base value. Low and high keep their configured ratio to the
    base, so the range moves with the slider.
    """

    def __init__(self, cfg: AssumptionConfig, overrides: dict[str, float] | None = None):
        self.cfg = cfg
        self.overrides = dict(overrides or {})

    def base(self, key: str) -> float:
        return float(self.overrides.get(key, self.cfg.parameters[key].value))

    def get(self, key: str, scenario: Scenario = "base") -> float:
        p = self.cfg.parameters[key]
        base = self.base(key)
        if scenario == "base":
            return base
        bound = p.low if scenario == "low" else p.high
        if bound is None or p.value == 0:
            return base
        return base * bound / p.value

    def with_override(self, key: str, value: float) -> "Params":
        return Params(self.cfg, {**self.overrides, key: value})

    def key(self) -> tuple:
        """Hashable fingerprint, for caching."""
        return tuple(sorted(self.overrides.items()))


def load_dotenv(path: Path | None = None) -> None:
    """Read KEY=value lines from .env into the environment. Existing variables win."""
    path = path or ROOT / ".env"
    if os.environ.get("OOH_NO_DOTENV") or not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


def env_key(name: str) -> str | None:
    """Return an environment variable if set and non-empty (after loading .env once)."""
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        load_dotenv()
        _DOTENV_LOADED = True
    value = os.environ.get(name, "").strip()
    return value or None


_DOTENV_LOADED = False
