"""The labelled metric object every output uses: {value, low, high, label, source}."""

from __future__ import annotations

from dataclasses import asdict, dataclass

LABEL_RANK = {"VERIFIED": 0, "ESTIMATE": 1, "ASSUMPTION": 2, "SAMPLE": 3, "CONCEPT": 4}


@dataclass
class Metric:
    value: float
    low: float
    high: float
    label: str
    source: str
    unit: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def scaled(self, factor: float, source: str | None = None, unit: str | None = None) -> "Metric":
        return Metric(self.value * factor, self.low * factor, self.high * factor, self.label,
                      source or self.source, unit if unit is not None else self.unit)


def weakest(*labels: str) -> str:
    """The least certain label wins: a number built on SAMPLE input is SAMPLE."""
    return max(labels, key=lambda l: LABEL_RANK.get(l, 1))


def fmt_num(x: float) -> str:
    """Compact human number: 1,234 / 12.3k / 1.23M."""
    ax = abs(x)
    if ax >= 1e6:
        return f"{x / 1e6:.2f}M"
    if ax >= 1e4:
        return f"{x / 1e3:.1f}k"
    if ax >= 100:
        return f"{x:,.0f}"
    return f"{x:.2f}" if ax < 10 else f"{x:.1f}"
