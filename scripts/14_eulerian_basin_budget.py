#!/usr/bin/env python3
"""
Eulerian Basin Moisture Budget Engine
Uses divergence theorem on HydroBASINS L6 polygons with ERA5 surface data.
Computes per-basin: net flux, sink (P-E), storage change, neighbor transport.

Method:
  Moisture budget:  d(TCWV)/dt = E - P - ∇·(IVT)
  Rearranged:  P - E = -∇·(IVT) - d(TCWV)/dt
  Sink ≡ net precipitation = convergence - storage change

  where convergence = -vimdf (ERA5's vertically integrated moisture divergence,
  with sign flipped: positive = moisture converging into column)

References:
  - van der Ent et al. (2010), WAM-2layers
  - ERA5: viwve, viwvn, vimdf, tcwv, e, tp
"""

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio.features
import xarray as xr
from shapely.geometry import shape

# ── config ──────────────────────────────────────────────────
PROJECT = Path("/Users/gac/research_projects/atmospheric_rivers_orinoquia")
ERA5_ROOT = Path("/Volumes/GC_SDD1/ncdata/era5_sa")
BASIN_GPKG = PROJECT / "data/hydrobasins/orinoco_l6_basins.gpkg"
OUT_DIR = PROJECT / "results/eulerian_budgets"

# ERA5 surface variable mapping
SFC_INSTANT_VARS = {
    "viwve": "viwve",  # IVT eastward  [kg m-1 s-1]
    "viwvn": "viwvn",  # IVT northward [kg m-1 s-1]
    "vimdf": "vimdf",  # moisture flux divergence [kg m-2 s-1]
    "tcwv": "tcwv",    # total column water vapour [kg m-2]
}
SFC_ACCUM_VARS = {
    "e": "e",    # evaporation [m of water]
    "tp": "tp",  # total precipitation [m of water]
}
RHO_W = 1000.0  # water density [kg m-3] — convert m to kg m-2
SECONDS_PER_6H = 6 * 3600  # 21600 s


def load_basins():
    """Load HydroBASINS L6 basins, keep relevant columns."""
    gdf = gpd.read_file(BASIN_GPKG)
    gdf = gdf.to_crs("EPSG:4326")
    keep = ["HYBAS_ID", "PFAF_ID", "SUB_AREA", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]]
    return gdf


def rasterize_basin(gdf, lats, lons):
    """
    Rasterize all basin polygons onto the ERA5 lat/lon grid.
    Returns basin_mask: 2D array with basin index (0-based) per grid cell.
    0 = no basin / ocean.
    """
    n_basins = len(gdf)
    # Build list of (geometry, basin_index+1) for rasterio
    shapes = [(geom, idx + 1) for idx, geom in enumerate(gdf.geometry)]
    # Transform: ERA5 grid is regular lat/lon at 0.25°
    dx = float(lons[1] - lons[0])
    dy = float(lats[1] - lats[0])
    # rasterio expects transform from upper-left corner
    # ERA5 lats are descending (N→S), so lats[0] is northernmost
    north = float(lats[0]) + abs(dy) / 2
    west = float(lons[0]) - dx / 2
    transform = rasterio.transform.from_origin(west, north, abs(dx), abs(dy))
    mask = rasterio.features.rasterize(
        shapes,
        out_shape=(len(lats), len(lons)),
        transform=transform,
        fill=0,
        dtype=np.int32,
    )
    return mask, n_basins


def compute_monthly_budget(month_str, gdf, basin_mask, n_basins):
    """
    Compute per-basin moisture budget for a single month.
    Returns dict: hybas_id -> {budget fields}
    """
    year = month_str[:4]
    month = month_str[4:6]

    # Load surface data
    instant_path = ERA5_ROOT / "surface" / year / f"era5_sa_sfc_instant_{month_str}.nc"
    accum_path = ERA5_ROOT / "surface" / year / f"era5_sa_sfc_accum_{month_str}.nc"

    if not instant_path.exists() or not accum_path.exists():
        print(f"  SKIP {month_str}: missing surface files")
        return {}

    ds_i = xr.open_dataset(instant_path)
    ds_a = xr.open_dataset(accum_path)

    lats = ds_i.latitude.values
    lons = ds_i.longitude.values
    n_time = len(ds_i.valid_time)

    # Extract variables as numpy arrays (time, lat, lon)
    vimdf = ds_i["vimdf"].values  # divergence, kg m-2 s-1
    tcwv = ds_i["tcwv"].values    # total column, kg m-2
    viwve = ds_i["viwve"].values  # IVT east, kg m-1 s-1
    viwvn = ds_i["viwvn"].values  # IVT north, kg m-1 s-1
    evap = ds_a["e"].values       # evaporation, m
    precip = ds_a["tp"].values     # precipitation, m

    ds_i.close()
    ds_a.close()

    # ── Per-basin aggregation ──────────────────────────────
    # Pre-allocate: (n_basins, n_time)
    convergence = np.zeros((n_basins, n_time))  # -vimdf averaged over basin
    tcwv_mean = np.zeros((n_basins, n_time))
    ivt_east = np.zeros((n_basins, n_time))
    ivt_north = np.zeros((n_basins, n_time))
    evap_mean = np.zeros((n_basins, n_time))
    precip_mean = np.zeros((n_basins, n_time))
    n_cells = np.zeros(n_basins, dtype=np.int32)

    for b_idx in range(1, n_basins + 1):
        cell_mask = basin_mask == b_idx
        nc = cell_mask.sum()
        if nc == 0:
            continue
        n_cells[b_idx - 1] = nc
        # Spatial mean over basin cells
        # convergence = -vimdf (positive = moisture converging)
        convergence[b_idx - 1] = -vimdf[:, cell_mask].mean(axis=1)
        tcwv_mean[b_idx - 1] = tcwv[:, cell_mask].mean(axis=1)
        ivt_east[b_idx - 1] = viwve[:, cell_mask].mean(axis=1)
        ivt_north[b_idx - 1] = viwvn[:, cell_mask].mean(axis=1)
        evap_mean[b_idx - 1] = evap[:, cell_mask].mean(axis=1) * RHO_W  # m → kg m-2
        precip_mean[b_idx - 1] = precip[:, cell_mask].mean(axis=1) * RHO_W  # m → kg m-2

    # ── Temporal integration ───────────────────────────────
    # Storage change: d(TCWV)/dt (central difference)
    d_tcwv_dt = np.zeros_like(tcwv_mean)
    d_tcwv_dt[:, 1:-1] = (tcwv_mean[:, 2:] - tcwv_mean[:, :-2]) / (2 * SECONDS_PER_6H)
    d_tcwv_dt[:, 0] = (tcwv_mean[:, 1] - tcwv_mean[:, 0]) / SECONDS_PER_6H
    d_tcwv_dt[:, -1] = (tcwv_mean[:, -1] - tcwv_mean[:, -2]) / SECONDS_PER_6H

    # Sink = convergence - d(TCWV)/dt  [kg m-2 s-1]
    # This equals P - E by the moisture budget equation
    sink_rate = convergence - d_tcwv_dt

    # Time-integrated totals [kg m-2 over the month]
    # Integrate by summing rates × seconds per step
    conv_total = convergence.sum(axis=1) * SECONDS_PER_6H  # kg m-2
    d_tcwv_total = (tcwv_mean[:, -1] - tcwv_mean[:, 0])  # net storage change, kg m-2
    sink_total = sink_rate.sum(axis=1) * SECONDS_PER_6H  # kg m-2 (P-E)
    # ── Accumulated variables: difference to get rate ──────
    # ERA5 accum resets daily; values are cumulative over 6h
    # Diff consecutive steps on raw grid, then average over basins
    evap_rate_grid = np.diff(evap, axis=0)  # (n_time-1, lat, lon), m per 6h
    precip_rate_grid = np.diff(precip, axis=0)
    # Average over basins
    evap_rate_basin = np.zeros((n_basins, n_time - 1))
    precip_rate_basin = np.zeros((n_basins, n_time - 1))
    for b_idx in range(1, n_basins + 1):
        cell_mask = basin_mask == b_idx
        if cell_mask.sum() == 0:
            continue
        evap_rate_basin[b_idx - 1] = evap_rate_grid[:, cell_mask].mean(axis=1)
        precip_rate_basin[b_idx - 1] = precip_rate_grid[:, cell_mask].mean(axis=1)

    # Convert m → kg m-2 per time step, then integrate over month
    evap_total = evap_rate_basin.sum(axis=1) * RHO_W   # kg m-2
    precip_total = precip_rate_basin.sum(axis=1) * RHO_W

    # Mean IVT magnitude and direction
    ivt_mag = np.sqrt(ivt_east**2 + ivt_north**2).mean(axis=1)  # kg m-1 s-1
    ivt_dir = np.arctan2(np.mean(ivt_north, axis=1), np.mean(ivt_east, axis=1))
    ivt_dir_deg = np.degrees(ivt_dir) % 360

    # ── Build results ──────────────────────────────────────
    results = {}
    for b_idx, (_, row) in enumerate(gdf.iterrows()):
        hybas = str(int(row["HYBAS_ID"]))
        if n_cells[b_idx] == 0:
            continue
        area_m2 = float(row["SUB_AREA"]) * 1e6  # km² → m²

        # Convert kg m-2 to total kg over basin
        results[hybas] = {
            "hybas_id": hybas,
            "month": month_str,
            "sub_area_km2": float(row["SUB_AREA"]),
            "n_grid_cells": int(n_cells[b_idx]),
            # Fluxes [kg s-1 over basin]
            "convergence_kg_s": float(convergence[b_idx].mean()),
            "d_tcwv_dt_kg_s": float(d_tcwv_dt[b_idx].mean()),
            "sink_rate_kg_s": float(sink_rate[b_idx].mean()),
            # Monthly totals [kg over basin]
            "conv_total_kg": float(conv_total[b_idx]),
            "storage_change_kg": float(d_tcwv_total[b_idx]),
            "sink_total_kg": float(sink_total[b_idx]),
            "evap_total_kg": float(evap_total[b_idx]),
            "precip_total_kg": float(precip_total[b_idx]),
            # Volumetric [m³ water]
            "sink_total_m3": float(sink_total[b_idx] / RHO_W),
            "evap_total_m3": float(evap_total[b_idx] / RHO_W),
            "precip_total_m3": float(precip_total[b_idx] / RHO_W),
            # Mean IVT
            "ivt_magnitude_kg_ms": float(ivt_mag[b_idx]),
            "ivt_direction_deg": float(ivt_dir_deg[b_idx]),
            # Derived: sink as equivalent mm/day over basin
            "sink_mm_day": float(sink_rate[b_idx].mean() * 86400),  # kg m-2 s-1 → mm/day
            "evap_mm_day": float(evap_total[b_idx] / area_m2 * RHO_W
                                 / (n_time - 1) / (SECONDS_PER_6H / 86400)),
            "precip_mm_day": float(precip_total[b_idx] / area_m2 * RHO_W
                                   / (n_time - 1) / (SECONDS_PER_6H / 86400)),
        }

    return results


def main():
    parser = argparse.ArgumentParser(description="Eulerian basin moisture budget")
    parser.add_argument("--months", nargs="+", required=True,
                        help="Months as YYYYMM (e.g. 202301 202302)")
    parser.add_argument("--out", default=str(OUT_DIR),
                        help="Output directory")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load basins
    print("Loading HydroBASINS L6...")
    gdf = load_basins()
    print(f"  {len(gdf)} basins")

    # Use first available surface file to get grid
    first_month = args.months[0]
    year = first_month[:4]
    instant_path = ERA5_ROOT / "surface" / year / f"era5_sa_sfc_instant_{first_month}.nc"
    ds = xr.open_dataset(instant_path)
    lats = ds.latitude.values
    lons = ds.longitude.values
    ds.close()

    # Rasterize basins onto ERA5 grid
    print(f"Rasterizing basins onto {len(lats)}×{len(lons)} grid...")
    basin_mask, n_basins = rasterize_basin(gdf, lats, lons)
    cells_with_basin = (basin_mask > 0).sum()
    print(f"  {cells_with_basin} grid cells covered by basins")
    print(f"  {n_basins} unique basin IDs in mask")

    # Process each month
    all_results = {}
    for month_str in args.months:
        print(f"\nProcessing {month_str}...")
        results = compute_monthly_budget(month_str, gdf, basin_mask, n_basins)
        all_results[month_str] = results
        n_with = sum(1 for r in results.values() if r["n_grid_cells"] > 0)
        print(f"  {n_with} basins with data")

    # Flatten: key = "{hybas_id}:{month}"
    flat_results = {}
    for month_str, results in all_results.items():
        for hybas, rec in results.items():
            flat_results[f"{hybas}:{month_str}"] = rec

    # Save
    out_json = OUT_DIR / f"eulerian_budgets_{args.months[0]}_{args.months[-1]}.json"
    with open(out_json, "w") as f:
        json.dump(flat_results, f, indent=2)
    print(f"\nSaved {len(flat_results)} basin-months to {out_json}")


if __name__ == "__main__":
    main()
