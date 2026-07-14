"""Regenerate AllocSignal's deterministic fictional CSV examples."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SEED = 20260714


CHANNEL_ROWS = [
    ["Paid search", 140000, 50000, 260000, 0, 920000, 150000, 1.25, 1.05, "false"],
    ["Online video", 110000, 40000, 220000, 0, 720000, 135000, 1.60, 1.12, "false"],
    ["Retail media", 90000, 35000, 170000, 0, 480000, 90000, 1.10, 1.03, "false"],
    ["Out of home", 80000, 70000, 130000, 0, 350000, 120000, 1.80, 1.15, "true"],
    ["CRM", 45000, 20000, 100000, 0, 240000, 45000, 0.85, 1.25, "false"],
    ["Field marketing", 125000, 90000, 180000, 0, 520000, 140000, 1.45, 1.10, "false"],
]


def write_channel_plan() -> None:
    headers = [
        "channel",
        "current_spend",
        "min_spend",
        "max_spend",
        "floor_response",
        "ceiling_response",
        "half_saturation",
        "shape",
        "long_run_multiplier",
        "fixed",
    ]
    with (EXAMPLES / "demo_channel_plan.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(CHANNEL_ROWS)


def write_panel() -> None:
    rng = np.random.default_rng(SEED)
    regions = [
        "Northbay",
        "Eastport",
        "Southfield",
        "Westhaven",
        "Pinecrest",
        "Lakeview",
        "Riverton",
        "Hillford",
        "Brookmere",
        "Cedarvale",
        "Stonebridge",
        "Fairmont",
    ]
    season = [-18, 5, 12, 26]
    with (EXAMPLES / "demo_marketing_panel.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "region",
                "period",
                "sales",
                "paid_search",
                "online_display",
                "traditional_media",
                "distribution",
                "price_index",
            ]
        )
        for index, region in enumerate(regions):
            potential = 430 + 35 * index + rng.normal(0, 12)
            typical_search = 20 + 0.10 * potential
            typical_display = 16 + 0.045 * potential
            for period_index in range(12):
                quarter = period_index % 4
                search = max(
                    5,
                    typical_search
                    + 2.4 * period_index
                    + 5 * np.sin((period_index + index) / 2)
                    + rng.normal(0, 5),
                )
                display = max(
                    5,
                    typical_display
                    + 1.4 * period_index
                    + 4 * np.cos((period_index + 2 * index) / 3)
                    + rng.normal(0, 4),
                )
                traditional = max(
                    5,
                    54
                    + 0.025 * potential
                    + (10 if quarter in (2, 3) else -4)
                    + rng.normal(0, 6),
                )
                distribution = min(
                    0.96,
                    max(0.42, 0.50 + 0.00032 * potential + 0.008 * period_index + rng.normal(0, 0.018)),
                )
                price_index = 1.03 - 0.0025 * period_index + 0.015 * np.sin(index) + rng.normal(0, 0.012)
                sales = (
                    potential
                    + 1.30 * search
                    + 0.72 * display
                    + 0.34 * traditional
                    + 390 * distribution
                    - 145 * price_index
                    + season[quarter]
                    + 4 * period_index
                    + rng.normal(0, 18)
                ) * 1000
                year = 2024 + period_index // 4
                writer.writerow(
                    [
                        region,
                        f"{year}-Q{quarter + 1}",
                        round(sales),
                        round(search * 1000),
                        round(display * 1000),
                        round(traditional * 1000),
                        f"{distribution:.3f}",
                        f"{price_index:.3f}",
                    ]
                )


def main() -> None:
    EXAMPLES.mkdir(exist_ok=True)
    write_channel_plan()
    write_panel()
    print(f"Wrote deterministic examples to {EXAMPLES}")


if __name__ == "__main__":
    main()
