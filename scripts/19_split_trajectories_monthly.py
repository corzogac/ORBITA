#!/usr/bin/env python3
"""
Split the massive trajectory CSV into 12 monthly files + pre-computed mean paths.
Reduces browser memory from 2.6M rows to ~220K per month (~85% reduction).

Outputs:
  assets/trajectories_YYYYMM.csv.gz   — per-month trajectory points (gzipped)
  assets/mean_paths_YYYYMM.json       — pre-computed agreement-weighted mean paths
  assets/basin_arrival_counts.json    — per-basin arrival counts for dropdown ★
"""

import gzip, json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/gac/research_projects/atmospheric_rivers_orinoquia")
ASSETS = ROOT / "results/trajectory_platform/assets"
PARQUET = ROOT / "results/tables/trajectory_ensemble_2023_available_2d_rk4.parquet"


def build_mean_paths(df: pd.DataFrame) -> dict:
    """Pre-compute agreement-weighted mean paths per basin per month."""
    # Extract arrival basin: HYBAS_ID at hour_back=0
    arrivals = df[df["hour_back"] == 0][["trajectory_id", "HYBAS_ID"]].copy()
    arrivals = arrivals.rename(columns={"HYBAS_ID": "arrival_HYBAS_ID"})
    arrivals["arrival_HYBAS_ID"] = arrivals["arrival_HYBAS_ID"].fillna(0).astype(int).astype(str)
    
    # Merge arrival basin back
    df = df.merge(arrivals, on="trajectory_id", how="left")
    
    mean_paths = {}
    for (month, hybas), group in df.groupby(["month", "arrival_HYBAS_ID"]):
        if hybas == "0": continue
        key = f"{hybas}:{month}"
        by_hour = {}
        for _, row in group.iterrows():
            h = int(row["hour_back"])
            lat = float(row["lat"]); lon = float(row["lon"])
            if not (np.isfinite(lat) and np.isfinite(lon)): continue
            if h not in by_hour: by_hour[h] = []
            by_hour[h].append((lat, lon))
        
        path = []
        for h in sorted(by_hour.keys(), reverse=True):
            pts = by_hour[h]
            mean_lat = sum(p[0] for p in pts) / len(pts)
            mean_lon = sum(p[1] for p in pts) / len(pts)
            disp = sum(
                np.sqrt((p[0]-mean_lat)**2 + (p[1]-mean_lon)**2) * 111.32
                for p in pts
            ) / len(pts) if len(pts) > 1 else 0
            score = len(pts) / (1 + disp/25)
            path.append({
                "h": h, "lat": round(mean_lat, 4), "lon": round(mean_lon, 4),
                "disp": round(disp, 1), "n": len(pts), "score": round(score, 3)
            })
        
        if path:
            mean_paths[key] = path
    
    return mean_paths


def main():
    print("Loading combined Parquet...")
    df = pd.read_parquet(PARQUET)
    print(f"  {len(df)} rows, {df.trajectory_id.nunique()} trajectories")
    
    # ── Split by month ──────────────────────────
    months = sorted(df["month"].unique())
    for month in months:
        month_df = df[df["month"] == month].copy()
        # Reduce: only keep columns needed for the map
        keep = ["trajectory_id", "target", "release_date", "release_time_utc",
                "hour_back", "lat", "lon", "pressure_hpa", "HYBAS_ID",
                "arrival_HYBAS_ID", "arrival_basin_name", "month"]
        month_df = month_df[[c for c in keep if c in month_df.columns]]
        
        csv_path = ASSETS / f"trajectories_{month.replace('-','')}.csv"
        month_df.to_csv(csv_path, index=False)
        
        # Gzip
        gz_path = ASSETS / f"trajectories_{month.replace('-','')}.csv.gz"
        with open(csv_path, 'rb') as f_in:
            with gzip.open(gz_path, 'wb', compresslevel=6) as f_out:
                f_out.write(f_in.read())
        
        csv_path.unlink()  # remove uncompressed
        size_mb = gz_path.stat().st_size / 1e6
        print(f"  {month}: {len(month_df)} rows, {month_df.trajectory_id.nunique()} traj → {gz_path.name} ({size_mb:.1f} MB)")
    
    # ── Pre-compute mean paths ──────────────────
    print("\nComputing mean paths per basin/month...")
    mean_paths = build_mean_paths(df)
    mp_path = ASSETS / "mean_paths.json"
    with open(mp_path, "w") as f:
        json.dump(mean_paths, f)
    print(f"  {len(mean_paths)} mean paths → {mp_path} ({mp_path.stat().st_size/1024:.0f} KB)")
    
    # ── Arrival counts ──────────────────────────
    arrivals_df = df[df["hour_back"] == 0].copy()
    arrivals_df["arrival_basin"] = arrivals_df["HYBAS_ID"].fillna(0).astype(int).astype(str)
    arr_counts = arrivals_df[arrivals_df["arrival_basin"] != "0"].groupby("arrival_basin").size()
    ac_path = ASSETS / "basin_arrival_counts.json"
    counts = {str(k): int(v) for k, v in arr_counts.items()}
    with open(ac_path, "w") as f:
        json.dump(counts, f)
    print(f"  {len(counts)} basins with arrivals → {ac_path}")

    print("\nDone. Upload with:")
    print("  gsutil -m cp results/trajectory_platform/assets/trajectories_*.csv.gz gs://orbita-platform-data/orinoquia/assets/")
    print("  gsutil -m cp results/trajectory_platform/assets/mean_paths.json gs://orbita-platform-data/orinoquia/assets/")
    print("  gsutil -m cp results/trajectory_platform/assets/basin_arrival_counts.json gs://orbita-platform-data/orinoquia/assets/")
    print("  gsutil setmeta -h 'Content-Encoding:gzip' -h 'Content-Type:text/csv' gs://orbita-platform-data/orinoquia/assets/trajectories_*.csv.gz")


if __name__ == "__main__":
    main()
