#!/usr/bin/env python3
"""Create coverage_matrix.csv from the PLAN.md reference values."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

ROWS = [
    ("basic", "auto_collision", 15000, 1000, "racing|commercial_use", "Standard collision coverage"),
    ("standard", "auto_collision", 25000, 500, "racing|commercial_use", "Enhanced collision coverage"),
    ("premium", "auto_collision", 50000, 250, "racing", "Comprehensive collision with low deductible"),
    ("basic", "auto_comprehensive", 10000, 1000, "wear_and_tear|mechanical", "Theft and vandalism only"),
    ("standard", "auto_comprehensive", 20000, 500, "wear_and_tear|mechanical", "Includes weather damage"),
    ("premium", "auto_comprehensive", 40000, 250, "wear_and_tear", "Full comprehensive coverage"),
    ("basic", "home_fire", 100000, 2500, "arson|business_use", "Structure only"),
    ("standard", "home_fire", 250000, 1500, "arson|business_use", "Structure + contents"),
    ("premium", "home_fire", 500000, 1000, "arson", "Full replacement value"),
    ("basic", "health_surgery", 50000, 5000, "cosmetic|experimental", "Emergency procedures only"),
    ("standard", "health_surgery", 150000, 2500, "cosmetic|experimental", "Planned and emergency"),
    ("premium", "health_surgery", "unlimited", 1000, "cosmetic", "All medically necessary procedures"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate coverage_matrix.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "coverage_matrix.csv",
    )
    return parser.parse_args()


def print_coverage_summary(rows: list[tuple]) -> None:
    tier_counts = Counter(row[0] for row in rows)
    claim_type_counts = Counter(row[1] for row in rows)
    print(
        "Coverage matrix summary -> rows: {total}, tiers [{tiers}], claim_types [{claims}]".format(
            total=len(rows),
            tiers=", ".join(f"{k}:{v}" for k, v in tier_counts.most_common()),
            claims=", ".join(f"{k}:{v}" for k, v in claim_type_counts.most_common()),
        )
    )


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["policy_tier", "claim_type", "coverage_limit", "deductible", "exclusions", "notes"])
        for row in ROWS:
            writer.writerow(row)
    print_coverage_summary(ROWS)
    print(f"Wrote coverage matrix to {args.output}")


if __name__ == "__main__":
    main()
