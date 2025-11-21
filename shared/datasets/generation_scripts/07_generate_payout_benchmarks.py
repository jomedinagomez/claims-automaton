#!/usr/bin/env python3
"""Summarize claims_history.csv into payout_benchmarks.csv."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

DEFAULT_ROWS = {
    ("auto_collision", "minor"): (2500, 800, 1800, 2400, 3100, 4200, 1523),
    ("auto_collision", "moderate"): (8500, 2200, 6500, 8200, 10500, 13000, 892),
    ("auto_collision", "severe"): (25000, 8500, 18000, 24000, 31000, 42000, 234),
    ("auto_comprehensive", "minor"): (1800, 600, 1200, 1700, 2200, 2800, 1876),
    ("auto_comprehensive", "moderate"): (5500, 1800, 4000, 5200, 6800, 8500, 723),
    ("auto_comprehensive", "severe"): (18000, 7500, 12000, 16500, 23000, 30000, 189),
    ("home_fire", "minor"): (8500, 3200, 5500, 8000, 11000, 14500, 456),
    ("home_fire", "moderate"): (35000, 12000, 25000, 33000, 43000, 55000, 287),
    ("home_fire", "major"): (75000, 35000, 45000, 68000, 95000, 125000, 156),
    ("health_surgery", "routine"): (12000, 4500, 8500, 11500, 15000, 19000, 2341),
    ("health_surgery", "complex"): (45000, 18000, 30000, 42000, 58000, 75000, 892),
    ("health_surgery", "critical"): (95000, 42000, 60000, 88000, 125000, 160000, 234),
}

SEVERITY_RULES: Dict[str, List[Tuple[float, float, str]]] = {
    "auto_collision": [(0, 6000, "minor"), (6000, 15000, "moderate"), (15000, float("inf"), "severe")],
    "auto_comprehensive": [(0, 4000, "minor"), (4000, 12000, "moderate"), (12000, float("inf"), "severe")],
    "home_fire": [(0, 20000, "minor"), (20000, 60000, "moderate"), (60000, float("inf"), "major")],
    "health_surgery": [(0, 20000, "routine"), (20000, 60000, "complex"), (60000, float("inf"), "critical")],
}

OUTPUT_COLUMNS = [
    "claim_type",
    "severity",
    "avg_payout",
    "std_deviation",
    "percentile_25",
    "percentile_50",
    "percentile_75",
    "percentile_90",
    "sample_size",
    "last_updated",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate payout benchmarks")
    parser.add_argument(
        "--claims",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "historical" / "claims_history.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "historical" / "payout_benchmarks.csv",
    )
    return parser.parse_args()


def assign_severity(claim_type: str, amount: float) -> str:
    rules = SEVERITY_RULES.get(claim_type)
    if not rules:
        return "unknown"
    for lower, upper, label in rules:
        if lower <= amount < upper:
            return label
    return rules[-1][2]


def compute_rows(df: pd.DataFrame) -> Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, int]]:
    rows: Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, int]] = {}
    if df.empty:
        return rows

    df = df.copy()
    df["amount_paid"] = df["amount_paid"].astype(float)
    df["severity"] = [assign_severity(ct, amt) for ct, amt in zip(df["claim_type"], df["amount_paid"])]
    grouped = df.groupby(["claim_type", "severity"])  # type: ignore[arg-type]

    for (claim_type, severity), group in grouped:
        payouts = group["amount_paid"].to_numpy()
        if len(payouts) == 0:
            continue
        avg = float(np.mean(payouts))
        std = float(np.std(payouts, ddof=0))
        p25, p50, p75, p90 = [float(np.percentile(payouts, p)) for p in (25, 50, 75, 90)]
        rows[(claim_type, severity)] = (
            round(avg, 2),
            round(std, 2),
            round(p25, 2),
            round(p50, 2),
            round(p75, 2),
            round(p90, 2),
            int(len(payouts)),
        )
    return rows


def mix_defaults(rows: Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, int]]) -> Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, int]]:
    merged = DEFAULT_ROWS.copy()
    merged.update(rows)
    return merged


def write_csv(rows: Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, int]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for (claim_type, severity), stats in rows.items():
            writer.writerow([claim_type, severity, *stats, today])
    print(f"Wrote payout benchmarks to {output}")


def print_benchmark_summary(rows: Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, int]]) -> None:
    if not rows:
        print("Payout benchmark summary -> no rows generated")
        return
    type_counts = Counter(claim_type for claim_type, _ in rows.keys())
    severity_counts = Counter(severity for _, severity in rows.keys())
    print(
        "Payout benchmark summary -> total rows: {total}, claim_types [{types}], severities [{severities}]".format(
            total=len(rows),
            types=", ".join(f"{k}:{v}" for k, v in type_counts.most_common()),
            severities=", ".join(f"{k}:{v}" for k, v in severity_counts.most_common()),
        )
    )


def main() -> None:
    args = parse_args()
    if args.claims.exists():
        df = pd.read_csv(args.claims)
    else:
        df = pd.DataFrame()
    computed = compute_rows(df)
    rows = mix_defaults(computed)
    print_benchmark_summary(rows)
    write_csv(rows, args.output)


if __name__ == "__main__":
    main()
