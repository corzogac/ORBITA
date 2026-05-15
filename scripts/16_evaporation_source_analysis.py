#!/usr/bin/env python3
"""
Evaporation Source Region Analysis
Identifies "healthy evaporation regions" that contribute to flying rivers.

Method:
  1. Per-basin monthly mean evaporation (mm/day) from ERA5 surface data
  2. Standard minimum: 10th percentile across all basins per month
  3. Bonus evaporation = actual - minimum (excess above baseline)
  4. Rank basins by total bonus evaporation (source contribution)
  5. Seasonal consistency: basins with consistently high bonus across months

Outputs:
  - basin_evaporation.csv: per-basin×month evaporation metrics
  - evaporation_sources.geojson: basin polygons styled by source intensity
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

PROJECT = Path("/Users/gac/research_projects/atmospheric_rivers_orinoquia")
BUDGET_DIR = PROJECT / "results/eulerian_budgets"
BASIN_GPKG = PROJECT / "data/hydrobasins/orinoco_l6_basins.gpkg"
ASSETS_DIR = PROJECT / "results/trajectory_platform/assets"


def load_budgets(budget_json):
    """Load flat budget JSON, return DataFrame."""
    with open(budget_json) as f:
        data = json.load(f)

    rows = []
    for key, rec in data.items():
        hybas, month = key.split(":") if ":" in key else (rec.get("hybas_id", ""), rec.get("month", ""))
        rows.append({
            "hybas_id": hybas,
            "month": month,
            "sub_area_km2": rec.get("sub_area_km2", 0),
            "sink_mm_day": rec.get("sink_mm_day", 0),
            "evap_mm_day": rec.get("evap_mm_day", 0),
            "precip_mm_day": rec.get("precip_mm_day", 0),
            "ivt_magnitude_kg_ms": rec.get("ivt_magnitude_kg_ms", 0),
            "ivt_direction_deg": rec.get("ivt_direction_deg", 0),
        })
    return pd.DataFrame(rows)


def compute_evaporation_sources(df):
    """
    Compute moisture source metrics using TCWV and convergence.
    
    Since ERA5 'e' (evaporation) is near-zero or negative over tropical forests,
    we use total column water vapor (TCWV via sink) and convergence as proxies
    for moisture source potential.
    
    Standard minimum: for each month, the 10th percentile of basin sink (P-E).
    Healthy source = basin with consistently high moisture convergence 
    (negative sink, i.e., net moisture export to atmosphere).
    """
    months = sorted(df["month"].unique())
    
    # Use sink_mm_day: negative = net evaporation (source), positive = net precip (sink)
    # Source basins = negative sink (moisture export to atmosphere)
    df = df.copy()
    df["moisture_export"] = -df["sink_mm_day"]  # positive = net moisture leaving basin
    
    # Per-month baseline for moisture export (10th percentile)
    baseline = {}
    for m in months:
        month_data = df[df["month"] == m]["moisture_export"]
        baseline[m] = np.percentile(month_data, 10)
    
    df["export_baseline"] = df["month"].map(baseline)
    df["bonus_export"] = df["moisture_export"] - df["export_baseline"]
    df["bonus_export"] = df["bonus_export"].clip(lower=0)
    
    # Per-basin aggregation
    basin_stats = df.groupby("hybas_id").agg(
        mean_export=("moisture_export", "mean"),
        max_export=("moisture_export", "max"),
        total_bonus=("bonus_export", "sum"),
        mean_bonus=("bonus_export", "mean"),
        n_months=("month", "count"),
        months_above=("bonus_export", lambda x: (x > 0).sum()),
        sub_area_km2=("sub_area_km2", "first"),
        mean_ivt=("ivt_magnitude_kg_ms", "mean"),
        dominant_ivt_dir=("ivt_direction_deg", lambda x: np.mean(np.deg2rad(x))),
    ).reset_index()
    
    basin_stats["dominant_ivt_dir_deg"] = np.rad2deg(basin_stats["dominant_ivt_dir"]) % 360
    basin_stats = basin_stats.drop(columns=["dominant_ivt_dir"])
    
    q75 = basin_stats["mean_bonus"].quantile(0.75)
    q50 = basin_stats["mean_bonus"].quantile(0.50)
    
    def classify(row):
        if row["mean_bonus"] >= q75 and row["months_above"] >= len(months) * 0.7:
            return "primary_source"
        elif row["mean_bonus"] >= q50:
            return "secondary_source"
        elif row["mean_export"] > 0:
            return "contributor"
        return "minimal"
    
    basin_stats["source_class"] = basin_stats.apply(classify, axis=1)
    basin_stats["mean_evap"] = basin_stats["mean_export"]  # for backward compat in GeoJSON
    basin_stats["mean_bonus"] = basin_stats["mean_bonus"]
    
    return basin_stats, baseline


def build_geojson(basin_stats, gdf):
    """Merge basin stats into GeoJSON for the map."""
    gdf = gdf.copy()
    gdf["HYBAS_ID"] = gdf["HYBAS_ID"].astype(str)
    basin_stats["hybas_id"] = basin_stats["hybas_id"].astype(str)
    
    merged = gdf.merge(basin_stats, left_on="HYBAS_ID", right_on="hybas_id", how="left")
    
    # Keep only needed columns
    keep = ["HYBAS_ID", "PFAF_ID", "SUB_AREA", "mean_evap", "mean_bonus", 
            "total_bonus", "source_class", "months_above", "dominant_ivt_dir_deg",
            "mean_ivt", "geometry"]
    merged = merged[[c for c in keep if c in merged.columns]]
    
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-json", required=True)
    parser.add_argument("--out-dir", default=str(ASSETS_DIR))
    args = parser.parse_args()

    print("Loading budgets...")
    df = load_budgets(args.budget_json)
    print(f"  {len(df)} basin-months, {df['hybas_id'].nunique()} basins, {df['month'].nunique()} months")

    print("Computing evaporation sources...")
    basin_stats, baseline = compute_evaporation_sources(df)
    
    # Summary
    classes = basin_stats["source_class"].value_counts()
    for cls, count in classes.items():
        print(f"  {cls}: {count} basins")

    print(f"\nMonthly evaporation baseline (10th percentile):")
    for m, val in sorted(baseline.items()):
        print(f"  {m}: {val:.4f} mm/day")

    # Top source basins
    print("\nTop 10 evaporation source basins:")
    top = basin_stats.nlargest(10, "mean_bonus")
    for _, row in top.iterrows():
        print(f"  HB6_{row['hybas_id']}: +{row['mean_bonus']:.3f} mm/d bonus, "
              f"mean evap {row['mean_evap']:.3f} mm/d, "
              f"area {row['sub_area_km2']:.0f} km², "
              f"{row['months_above']}/{row['n_months']} months above baseline")

    # Save CSV
    csv_path = Path(args.out_dir) / "basin_evaporation_sources.csv"
    basin_stats.to_csv(csv_path, index=False)
    print(f"\nSaved {len(basin_stats)} basins to {csv_path}")

    # Build GeoJSON
    print("Building GeoJSON layer...")
    gdf = gpd.read_file(BASIN_GPKG)
    geo = build_geojson(basin_stats, gdf)
    
    # Simplify for web
    geo["geometry"] = geo["geometry"].simplify(0.02, preserve_topology=True)
    
    # Convert to GeoJSON dict
    geojson_dict = json.loads(geo.to_json())
    
    # Add style properties for the map
    color_map = {
        "primary_source": "#ff6b6b",
        "secondary_source": "#f9c74f", 
        "contributor": "#93c5fd",
        "minimal": "#1d4e89",
    }
    opacity_map = {
        "primary_source": 0.55,
        "secondary_source": 0.40,
        "contributor": 0.25,
        "minimal": 0.08,
    }
    
    for feat in geojson_dict["features"]:
        props = feat["properties"]
        cls = props.get("source_class", "minimal")
        props["fill_color"] = color_map.get(cls, "#1d4e89")
        props["fill_opacity"] = opacity_map.get(cls, 0.08)
        props["evap_label"] = (
            f"{props.get('mean_evap', 0):.3f} mm/d"
            if props.get("mean_evap") and props["mean_evap"] > 0
            else "no data"
        )
    
    geo_path = Path(args.out_dir) / "evaporation_sources.geojson"
    with open(geo_path, "w") as f:
        json.dump(geojson_dict, f)
    print(f"Saved GeoJSON to {geo_path}")

    # Save baseline
    baseline_path = Path(args.out_dir) / "evaporation_baseline.json"
    with open(baseline_path, "w") as f:
        json.dump({"baseline_mm_day": baseline, "n_months": len(baseline)}, f, indent=2)
    print(f"Saved baseline to {baseline_path}")


if __name__ == "__main__":
    main()
