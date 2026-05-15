#!/usr/bin/env python3
"""Prepare HydroBASINS level 6 data for basin-click trajectory platform.

Downloads South America HydroBASINS L6 if needed, filters to the project
Orinoquia/near-Andes bounding box, and writes GeoPackage + browser GeoJSON.
"""

from __future__ import annotations

import json
import logging
import subprocess
import zipfile
from pathlib import Path

import geopandas as gpd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "hydrobasins"
LEVEL = 6
URL = "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_sa_lev06_v1c.zip"
ZIP_PATH = DATA_DIR / "hybas_sa_lev06_v1c.zip"
EXTRACT_DIR = DATA_DIR / "hybas_sa_lev06_v1c"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def load_bbox() -> list[float]:
    cfg_path = PROJECT_ROOT / "config" / "hydrobasins.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return cfg["orinoco_basin"]["bbox"]


def ensure_download() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shp = EXTRACT_DIR / "hybas_sa_lev06_v1c.shp"
    if shp.exists():
        return shp
    if not ZIP_PATH.exists():
        log.info("Downloading %s", URL)
        subprocess.run(["curl", "-L", "--fail", "-o", str(ZIP_PATH), URL], check=True)
    log.info("Extracting %s", ZIP_PATH)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as zf:
        zf.extractall(EXTRACT_DIR)
    if not shp.exists():
        raise FileNotFoundError(shp)
    return shp


def main() -> None:
    shp = ensure_download()
    bbox = load_bbox()
    log.info("Reading %s", shp)
    gdf = gpd.read_file(shp)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")
    log.info("Total South America L6 basins: %s", len(gdf))

    # Keep a broad Orinoquia / eastern-Andes corridor. Extend westward to
    # include Manizales and adjacent Magdalena-Cauca arrival basins while still
    # keeping the file small enough for browser interaction.
    bbox = list(bbox)
    bbox[0] = min(bbox[0], -76.5)
    region = gdf.cx[bbox[0] : bbox[2], bbox[1] : bbox[3]].copy()
    log.info("Basins in project bbox: %s", len(region))

    # Compute centroids in a projected CRS, then transform back to lon/lat.
    centroids_ll = region.to_crs("EPSG:3857").geometry.centroid.to_crs("EPSG:4326")
    region["centroid_x"] = centroids_ll.x
    region["centroid_y"] = centroids_ll.y
    region["basin_name"] = "HB6_" + region["HYBAS_ID"].astype(str)
    # A clearer display label while we do not have official local names.
    region["display_name"] = region.apply(
        lambda r: f"HydroBASINS L6 {int(r.HYBAS_ID)} | Pfaf {int(r.PFAF_ID)} | {float(r.SUB_AREA):.0f} km²",
        axis=1,
    )

    keep = [
        "HYBAS_ID",
        "NEXT_DOWN",
        "MAIN_BAS",
        "SUB_AREA",
        "UP_AREA",
        "PFAF_ID",
        "ENDO",
        "COAST",
        "ORDER",
        "centroid_x",
        "centroid_y",
        "basin_name",
        "display_name",
        "geometry",
    ]
    out = region[keep].copy()

    gpkg = DATA_DIR / "orinoco_l6_basins.gpkg"
    geojson = DATA_DIR / "orinoco_l6_basins.geojson"
    log.info("Writing %s", gpkg)
    out.to_file(gpkg, layer="basins", driver="GPKG")
    simple = out.copy()
    simple["geometry"] = simple.geometry.simplify(0.006, preserve_topology=True)
    log.info("Writing %s", geojson)
    simple.to_file(geojson, driver="GeoJSON")

    main_basins = out.groupby("MAIN_BAS").agg(n_basins=("HYBAS_ID", "count"), total_area_km2=("SUB_AREA", "sum")).sort_values("total_area_km2", ascending=False)
    meta = {
        "source": str(shp),
        "version": "HydroBASINS v1c",
        "level": LEVEL,
        "bbox": bbox,
        "n_basins": int(len(out)),
        "n_main_bas_groups": int(out["MAIN_BAS"].nunique()),
        "total_area_km2": float(out["SUB_AREA"].sum()),
        "main_bas_groups": [
            {"code": int(idx), "n_basins": int(row.n_basins), "area_km2": float(row.total_area_km2)}
            for idx, row in main_basins.iterrows()
        ],
    }
    meta_path = DATA_DIR / "orinoco_l6_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("Done: %s L6 basins", len(out))


if __name__ == "__main__":
    main()
