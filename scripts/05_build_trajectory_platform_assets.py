#!/usr/bin/env python3
"""Build browser-ready assets for the basin-arrival flying-river platform.

The platform uses HydroBASINS Level 6 units. Trajectories are interpreted as
back-trajectories arriving at their hour_back == 0 basin; selecting a basin
filters trajectories whose arrival basin matches that selected L6 basin.

Physical transported-volume metrics are shown only when production rows include
`transport_volume_m3` or `uptake_volume_m3`. Until then, volume/contribution
panels are labeled as pending/proxy to avoid overclaiming.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def retag_trajectories_l6(traj: pd.DataFrame, basins: gpd.GeoDataFrame) -> pd.DataFrame:
    """Spatially tag all trajectory points and arrival points with HydroBASINS L6."""
    traj = traj.copy()
    geom = [Point(xy) for xy in zip(traj["lon"], traj["lat"])]
    pts = gpd.GeoDataFrame(traj, geometry=geom, crs="EPSG:4326")
    keep = [c for c in ["HYBAS_ID", "MAIN_BAS", "SUB_AREA", "PFAF_ID", "display_name", "basin_name", "geometry"] if c in basins.columns]
    tagged = gpd.sjoin(pts, basins[keep], how="left", predicate="within", rsuffix="l6")
    tagged = pd.DataFrame(tagged.drop(columns=[c for c in ["geometry", "index_l6", "index_right"] if c in tagged.columns]))

    # Rename possible joined columns robustly.
    if "HYBAS_ID_l6" in tagged.columns:
        tagged["HYBAS_ID"] = tagged["HYBAS_ID_l6"]
    if "MAIN_BAS_l6" in tagged.columns:
        tagged["MAIN_BAS"] = tagged["MAIN_BAS_l6"]
    if "SUB_AREA_l6" in tagged.columns:
        tagged["SUB_AREA"] = tagged["SUB_AREA_l6"]
    if "PFAF_ID_l6" in tagged.columns:
        tagged["PFAF_ID"] = tagged["PFAF_ID_l6"]
    if "display_name_l6" in tagged.columns:
        tagged["display_name"] = tagged["display_name_l6"]
    if "basin_name_l6" in tagged.columns:
        tagged["basin_name"] = tagged["basin_name_l6"]

    for c in [c for c in tagged.columns if c.endswith("_l6")]:
        tagged = tagged.drop(columns=[c])

    tagged["HYBAS_ID"] = tagged["HYBAS_ID"].astype("Int64")
    tagged["MAIN_BAS"] = tagged["MAIN_BAS"].astype("Int64")
    tagged["basin_name"] = tagged["HYBAS_ID"].apply(lambda x: f"HB6_{int(x)}" if pd.notna(x) else "ocean_or_outside_hydrobasins")
    tagged["display_name"] = tagged.apply(
        lambda r: r["display_name"] if isinstance(r.get("display_name"), str) and r.get("display_name") else r["basin_name"], axis=1
    )

    arrivals = tagged.loc[tagged["hour_back"].astype(float) == 0, ["trajectory_id", "HYBAS_ID", "basin_name", "display_name"]].copy()
    arrivals = arrivals.rename(
        columns={
            "HYBAS_ID": "arrival_HYBAS_ID",
            "basin_name": "arrival_basin_name",
            "display_name": "arrival_display_name",
        }
    )
    tagged = tagged.merge(arrivals, on="trajectory_id", how="left")
    tagged["arrival_HYBAS_ID"] = tagged["arrival_HYBAS_ID"].astype("Int64")
    return tagged


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "results" / "trajectory_platform"
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    basin_path = root / "data" / "hydrobasins" / "orinoco_l6_basins.gpkg"
    if not basin_path.exists():
        raise FileNotFoundError(f"Missing L6 basins. Run scripts/07_prepare_hydrobasins_l6.py first: {basin_path}")

    candidates = [
        root / "results" / "tables" / "trajectory_ensemble_2023_available_2d_rk4.parquet",
        root / "results" / "tables" / "trajectory_ensemble_2023_available_2d_rk4.csv",
        root / "results" / "tables" / "trajectory_ensemble_jan2023_2d_rk4.parquet",
        root / "results" / "tables" / "trajectory_ensemble_jan2023_2d_rk4.csv",
        root / "results" / "tables" / "trajectory_smoke_20230101_850hpa.csv",
    ]
    traj_path = next((p for p in candidates if p.exists()), candidates[-1])

    basins = gpd.read_file(basin_path, layer="basins")
    if basins.crs is None:
        basins = basins.set_crs("EPSG:4326")
    basins = basins.to_crs("EPSG:4326")

    keep_cols = [
        c
        for c in [
            "HYBAS_ID",
            "NEXT_DOWN",
            "MAIN_BAS",
            "SUB_AREA",
            "UP_AREA",
            "PFAF_ID",
            "ORDER",
            "display_name",
            "basin_name",
            "centroid_x",
            "centroid_y",
        ]
        if c in basins.columns
    ]
    browser_basins = basins[keep_cols + ["geometry"]].copy()
    browser_basins["name"] = browser_basins["HYBAS_ID"].apply(lambda x: f"HB6_{int(x)}")
    if "display_name" not in browser_basins.columns:
        browser_basins["display_name"] = browser_basins["name"]
    browser_basins["geometry"] = browser_basins.geometry.simplify(0.006, preserve_topology=True)
    basin_geojson = assets / "orinoco_l6_basins_simplified.geojson"
    browser_basins.to_file(basin_geojson, driver="GeoJSON")

    traj = pd.read_parquet(traj_path) if traj_path.suffix == ".parquet" else pd.read_csv(traj_path)
    if "release_date" not in traj.columns:
        traj["release_date"] = "2023-01-01"
    if "release_time_utc" not in traj.columns:
        traj["release_time_utc"] = traj["release_date"].astype(str) + "T00:00:00Z"
    if "trajectory_id" not in traj.columns:
        level = traj["pressure_hpa"].astype(str) if "pressure_hpa" in traj.columns else "unknown_level"
        base = traj["target"].astype(str) if "target" in traj.columns else "arrival"
        traj["trajectory_id"] = base + "_" + traj["release_date"].astype(str) + "_" + level
    if "level_hpa" not in traj.columns:
        traj["level_hpa"] = traj["pressure_hpa"] if "pressure_hpa" in traj.columns else None
    if "month" not in traj.columns:
        traj["month"] = pd.to_datetime(traj["release_date"]).dt.to_period("M").astype(str)
    traj["source_file"] = str(traj_path.relative_to(root))

    for col in [
        "evap_kg",
        "evap_mm_equiv",
        "uptake_kg",
        "uptake_volume_m3",
        "transport_volume_m3",
        "q_kgkg",
        "agreement_weight",
    ]:
        if col not in traj.columns:
            traj[col] = None

    tagged = retag_trajectories_l6(traj, basins)
    traj_csv = assets / "trajectories_platform_current.csv"
    tagged.to_csv(traj_csv, index=False)

    arrivals = tagged.loc[tagged["hour_back"].astype(float) == 0].copy()
    basin_options = arrivals.dropna(subset=["arrival_HYBAS_ID"]).groupby("arrival_HYBAS_ID").agg(
        n_trajectories=("trajectory_id", "nunique"),
        first_date=("release_date", "min"),
        last_date=("release_date", "max"),
        display_name=("arrival_display_name", "first"),
    ).reset_index()
    basin_options.to_csv(assets / "arrival_basin_options.csv", index=False)

    has_volume = tagged[["transport_volume_m3", "uptake_volume_m3"]].notna().any().any()
    summary = {
        "platform_status": "basin-arrival L6 platform; physical volume activates when transport_volume_m3 or uptake_volume_m3 exists",
        "trajectory_source": str(traj_path.relative_to(root)),
        "n_trajectories": int(tagged["trajectory_id"].nunique()),
        "n_points": int(len(tagged)),
        "dates_available": sorted(tagged["release_date"].astype(str).unique().tolist()),
        "months_available": sorted(tagged["month"].astype(str).unique().tolist()),
        "arrival_basins_available": int(basin_options["arrival_HYBAS_ID"].nunique()),
        "basins_available": int(len(browser_basins)),
        "basin_level": "HydroBASINS level 6",
        "has_physical_volume_m3": bool(has_volume),
        "agreement_method": "Selected L6 basin filters trajectories whose hour_back=0 arrival point is in that basin. Date window is selected month/date +/- day sliders. Mean path thickness scales with trajectory count and inverse dispersion by hour_back.",
        "volume_method": "If transport_volume_m3 exists: absolute m3 = mean/sum over selected arrivals; relative % = selected/path basin contribution divided by total over retained trajectories. If absent, UI reports pending/proxy only.",
    }
    (assets / "platform_metadata.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {basin_geojson}")
    print(f"Wrote {traj_csv}")
    print(f"Wrote {assets / 'arrival_basin_options.csv'}")
    print(f"Wrote {assets / 'platform_metadata.json'}")


if __name__ == "__main__":
    main()
