#!/usr/bin/env python3
"""Prepare HydroBASINS level 5 data for the Orinoquia atmospheric rivers project.

Extracts and filters basins relevant to the Orinoco drainage, saves as GeoPackage
for fast spatial queries during Lagrangian particle tagging.

Usage:
    python scripts/03_prepare_hydrobasins.py
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_config():
    with open(PROJECT_ROOT / "config" / "hydrobasins.yaml") as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    hb_cfg = cfg["hydrobasins"]
    orinoco_cfg = cfg["orinoco_basin"]

    # Input
    shp_path = PROJECT_ROOT / hb_cfg["local_path"] / f"hybas_sa_lev{hb_cfg['level']:02d}_v1c.shp"
    if not shp_path.exists():
        logger.error(f"Shapefile not found: {shp_path}")
        logger.error("Download first: python scripts/03_prepare_hydrobasins.py")
        sys.exit(1)

    logger.info(f"Reading {shp_path}...")
    gdf = gpd.read_file(shp_path)
    logger.info(f"Total South America L5 basins: {len(gdf)}")

    # Filter by Orinoco bounding box
    bbox = orinoco_cfg["bbox"]
    orinoco = gdf.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]].copy()
    logger.info(f"Basins in Orinoco bbox: {len(orinoco)}")

    # Identify the Orinoco main basin groups
    # The largest MAIN_BAS groups in the bbox are the Orinoco, Amazon (NW),
    # and Caribbean drainages. We keep all for now — the moisture tracking
    # may involve all of them.
    main_basins = orinoco.groupby("MAIN_BAS").agg(
        n_basins=("HYBAS_ID", "count"),
        total_area_km2=("SUB_AREA", "sum"),
    ).sort_values("total_area_km2", ascending=False)
    
    logger.info("\nMAIN_BAS groups in Orinoco bbox:")
    for idx, row in main_basins.iterrows():
        logger.info(f"  {idx}: {int(row['n_basins'])} basins, {row['total_area_km2']:.0f} km²")

    # Add centroid for fast KD-tree queries during particle tagging
    orinoco["centroid_x"] = orinoco.geometry.centroid.x
    orinoco["centroid_y"] = orinoco.geometry.centroid.y

    # Add simplified basin name from HYBAS_ID
    orinoco["basin_name"] = "HB_" + orinoco["HYBAS_ID"].astype(str)

    # Select columns for output
    output_cols = [
        "HYBAS_ID", "NEXT_DOWN", "MAIN_BAS", "SUB_AREA", "UP_AREA",
        "PFAF_ID", "ENDO", "COAST", "ORDER", "centroid_x", "centroid_y",
        "basin_name", "geometry",
    ]
    out_gdf = orinoco[output_cols].copy()

    # Save as GeoPackage (fast spatial queries) and GeoJSON (browser)
    out_dir = PROJECT_ROOT / "data" / "hydrobasins"
    out_dir.mkdir(parents=True, exist_ok=True)

    gpkg_path = out_dir / "orinoco_l5_basins.gpkg"
    geojson_path = out_dir / "orinoco_l5_basins.geojson"

    logger.info(f"\nSaving GeoPackage: {gpkg_path}")
    out_gdf.to_file(gpkg_path, layer="basins", driver="GPKG")

    logger.info(f"Saving GeoJSON (simplified): {geojson_path}")
    # Simplify for browser use (tolerance in degrees — ~1km at equator)
    gdf_simple = out_gdf.copy()
    gdf_simple["geometry"] = out_gdf.geometry.simplify(0.01)
    gdf_simple.to_file(geojson_path, driver="GeoJSON")

    # Summary
    logger.info(f"\n{'='*50}")
    logger.info(f"HydroBASINS preparation complete")
    logger.info(f"  Orinoco region basins (L5): {len(out_gdf)}")
    logger.info(f"  MAIN_BAS groups: {out_gdf['MAIN_BAS'].nunique()}")
    logger.info(f"  Total area: {out_gdf['SUB_AREA'].sum():.0f} km²")
    logger.info(f"  Outputs:")
    logger.info(f"    {gpkg_path}")
    logger.info(f"    {geojson_path}")

    # Write metadata
    meta = {
        "source": str(shp_path),
        "version": "HydroBASINS v1c",
        "level": hb_cfg["level"],
        "bbox_orinoco": bbox,
        "n_basins": len(out_gdf),
        "n_main_bas_groups": int(out_gdf["MAIN_BAS"].nunique()),
        "total_area_km2": float(out_gdf["SUB_AREA"].sum()),
        "main_bas_groups": [
            {"code": int(idx), "n_basins": int(row["n_basins"]), "area_km2": float(row["total_area_km2"])}
            for idx, row in main_basins.iterrows()
        ],
    }

    import json
    meta_path = out_dir / "orinoco_l5_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"    {meta_path}")


if __name__ == "__main__":
    main()
