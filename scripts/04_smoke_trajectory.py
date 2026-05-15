#!/usr/bin/env python3
"""Smoke test a first simple ERA5 back-trajectory.

This is Phase 2 prototype only:
- fixed pressure level (850 hPa)
- nearest ERA5 6-hourly time slice for wind, held constant for first smoke test
- 24-hour backward path from Bogotá and Manizales

The purpose is to validate file access, interpolation, coordinate conventions,
and path output before implementing full time-dependent RK4/3D trajectories.
"""

from pathlib import Path
import sys

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lagrangian_engine.data import ERA5Month
from lagrangian_engine.interpolation import FieldInterpolator
from lagrangian_engine.trajectory import integrate_isobaric_backward
from lagrangian_engine.basin_tagger import BasinTagger


def main():
    cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "era5_variables.yaml"))
    targets = yaml.safe_load(open(PROJECT_ROOT / "config" / "targets.yaml"))["targets"]

    era = ERA5Month(Path(cfg["storage"]["base_path"]), 2023, 1)
    ds = era.open_pressure(vars=("u", "v"))

    # Use one time slice first: Jan 1, 2023 00UTC
    u_interp = FieldInterpolator.from_dataset(ds, "u", time_index=0)
    v_interp = FieldInterpolator.from_dataset(ds, "v", time_index=0)

    def wind_sampler(p_hpa, lat, lon, step):
        return u_interp.sample(p_hpa, lat, lon), v_interp.sample(p_hpa, lat, lon)

    basin_path = PROJECT_ROOT / "data" / "hydrobasins" / "orinoco_l5_basins.gpkg"
    tagger = BasinTagger.from_gpkg(basin_path)

    out_rows = []
    for target_key, t in targets.items():
        traj = integrate_isobaric_backward(
            target_name=t["name"],
            lat0=t["lat"],
            lon0=t["lon"],
            pressure_hpa=850,
            wind_sampler=wind_sampler,
            n_steps=24,
            dt_hours=1.0,
        )
        for p in traj.points:
            tag = tagger.tag_point(p.lat, p.lon) or {}
            out_rows.append({
                "target": traj.target_name,
                "hour_back": p.hour_back,
                "lat": p.lat,
                "lon": p.lon,
                "pressure_hpa": p.pressure_hpa,
                "u_ms": p.u_ms,
                "v_ms": p.v_ms,
                "HYBAS_ID": tag.get("HYBAS_ID"),
                "MAIN_BAS": tag.get("MAIN_BAS"),
                "basin_name": tag.get("basin_name"),
            })

    out_dir = PROJECT_ROOT / "results" / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "trajectory_smoke_20230101_850hpa.csv"
    pd.DataFrame(out_rows).to_csv(out_csv, index=False)
    print(f"Wrote {out_csv}")
    print(pd.DataFrame(out_rows).groupby("target").tail(1).to_string(index=False))


if __name__ == "__main__":
    main()
