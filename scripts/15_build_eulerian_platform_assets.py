#!/usr/bin/env python3
"""
Build browser assets for the Eulerian Budget tab.
Reads per-month budget JSON files and produces:
  - basin_budgets.csv: one row per basin×month with key metrics
  - basin_summaries.json: per-basin multi-month stats
"""

import argparse
import json
from pathlib import Path

import pandas as pd

PROJECT = Path("/Users/gac/research_projects/atmospheric_rivers_orinoquia")
BUDGET_DIR = PROJECT / "results/eulerian_budgets"
PLATFORM_DIR = PROJECT / "results/trajectory_platform/assets"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-json", required=True,
                        help="Combined budget JSON file")
    parser.add_argument("--out-dir", default=str(PLATFORM_DIR))
    args = parser.parse_args()

    with open(args.budget_json) as f:
        data = json.load(f)

    # ── Build flat CSV for browser ─────────────────────────
    rows = []
    for key, rec in data.items():
        # key is "hybas_id:month" or just "hybas_id"
        if ":" in key:
            hybas, month = key.split(":")
            rec["hybas_id"] = hybas
            rec["month"] = month
        rows.append({
            "hybas_id": rec["hybas_id"],
            "month": rec["month"],
            "sub_area_km2": rec["sub_area_km2"],
            "sink_mm_day": round(rec["sink_mm_day"], 3),
            "convergence_kg_s": rec["convergence_kg_s"],
            "sink_rate_kg_s": rec["sink_rate_kg_s"],
            "sink_total_m3": round(rec["sink_total_m3"], 2),
            "ivt_magnitude_kg_ms": round(rec["ivt_magnitude_kg_ms"], 1),
            "ivt_direction_deg": round(rec["ivt_direction_deg"], 1),
            "evap_mm_day": round(rec.get("evap_mm_day", 0), 3),
            "precip_mm_day": round(rec.get("precip_mm_day", 0), 3),
        })

    df = pd.DataFrame(rows)
    csv_path = Path(args.out_dir) / "basin_budgets.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved {len(df)} rows to {csv_path}")

    # ── Build per-basin summary JSON ───────────────────────
    by_basin = {}
    for hybas, rec in data.items():
        month = rec["month"]
        if hybas not in by_basin:
            by_basin[hybas] = {
                "hybas_id": hybas,
                "sub_area_km2": rec["sub_area_km2"],
                "months": {},
            }
        by_basin[hybas]["months"][month] = {
            "sink_mm_day": rec["sink_mm_day"],
            "ivt_magnitude_kg_ms": rec["ivt_magnitude_kg_ms"],
            "ivt_direction_deg": rec["ivt_direction_deg"],
            "evap_mm_day": rec.get("evap_mm_day", 0),
            "precip_mm_day": rec.get("precip_mm_day", 0),
        }

    # Compute multi-month stats per basin
    for hybas, info in by_basin.items():
        sinks = [m["sink_mm_day"] for m in info["months"].values()]
        ivts = [m["ivt_magnitude_kg_ms"] for m in info["months"].values()]
        info["mean_sink_mm_day"] = round(sum(sinks) / len(sinks), 3)
        info["mean_ivt_kg_ms"] = round(sum(ivts) / len(ivts), 1)
        info["n_months"] = len(sinks)

    summary_path = Path(args.out_dir) / "basin_budget_summaries.json"
    with open(summary_path, "w") as f:
        json.dump(by_basin, f)
    print(f"Saved {len(by_basin)} basin summaries to {summary_path}")


if __name__ == "__main__":
    main()
