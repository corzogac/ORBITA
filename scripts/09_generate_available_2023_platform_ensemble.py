#!/usr/bin/env python3
"""Generate prototype trajectory ensembles for all complete downloaded 2023 ERA5 months.

This uses the existing 2D fixed-pressure RK4 prototype generator. It is not the
final 3D moisture-volume model, but it expands ORBITA month navigation beyond
January whenever u/v/q pressure-level files are available.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE_ERA5 = Path("/Volumes/GC_SDD1/ncdata/era5_sa/pressure_levels/2023")
TABLES = ROOT / "results" / "tables"


def complete_months() -> list[int]:
    months = []
    for month in range(1, 13):
        files = [BASE_ERA5 / f"era5_sa_pl_{var}_2023{month:02d}.nc" for var in ["u", "v", "q"]]
        if all(p.exists() and p.stat().st_size > 1_000_000 for p in files):
            months.append(month)
    return months


def run_month(month: int) -> Path:
    out = TABLES / f"trajectory_ensemble_2023{month:02d}_2d_rk4.parquet"
    if out.exists() and out.stat().st_size > 10_000:
        print(f"[skip] 2023-{month:02d}: {out}")
        return out
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "06_generate_january_trajectory_ensemble.py"),
        "--year",
        "2023",
        "--month",
        str(month),
        "--hours-back",
        "72",
        "--step-hours",
        "6",
        "--release-freq",
        "6h",
        "--levels",
        "850,700,500",
    ]
    print(f"[run] 2023-{month:02d}: {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    return out


def combine(paths: list[Path]) -> None:
    frames = []
    for p in paths:
        if p.exists():
            frames.append(pd.read_parquet(p))
    if not frames:
        raise RuntimeError("No monthly trajectory files found to combine")
    df = pd.concat(frames, ignore_index=True)
    out_parquet = TABLES / "trajectory_ensemble_2023_available_2d_rk4.parquet"
    out_csv = TABLES / "trajectory_ensemble_2023_available_2d_rk4.csv"
    df.to_parquet(out_parquet, index=False)
    df.to_csv(out_csv, index=False)
    summary = {
        "rows": int(len(df)),
        "trajectories": int(df["trajectory_id"].nunique()),
        "months": sorted(pd.to_datetime(df["release_date"]).dt.to_period("M").astype(str).unique().tolist()),
        "release_dates": [str(df["release_date"].min()), str(df["release_date"].max())],
        "source": "2D fixed-pressure RK4 prototype for complete downloaded 2023 months",
        "parquet": str(out_parquet.relative_to(ROOT)),
        "csv": str(out_csv.relative_to(ROOT)),
    }
    (TABLES / "trajectory_ensemble_2023_available_2d_rk4_summary.json").write_text(pd.Series(summary).to_json(indent=2), encoding="utf-8")
    print("[combined]", summary)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    months = complete_months()
    print(f"Complete ERA5 u/v/q months: {[f'2023-{m:02d}' for m in months]}")
    paths = [run_month(m) for m in months]
    combine(paths)


if __name__ == "__main__":
    main()
