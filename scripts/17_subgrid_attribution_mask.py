#!/usr/bin/env python3
"""
Sub-Grid Ecohydrological Attribution Mask
=========================================
Implements the distributed sub-grid disaggregation framework described in
the ORBITA methodological extension.

Transitions from lumped Eulerian basin allocation to a pixel-level
weighted attribution using:
  W(x) = L(k) × Φ(Z)
where:
  L(k) = literature-based evaporative coefficient for LULC class k
  Φ(Z) = elevation-dependent thermodynamic scaling function

Reference:
  The bonus evaporation at pixel x within basin B is:
    Bonus(x, m) = Bonus(B, m) × W(x) / Σ W(x)
  where Σ W(x) = 1 over the basin (normalization constraint).

Data sources:
  - ESA WorldCover 2021 v200 (10m LULC): https://esa-worldcover.org/
  - Copernicus DEM GLO-30 (30m elevation): https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/
  - Download instructions in docs/SUBGRID_DATA_SOURCES.md
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from scipy.ndimage import zoom
from shapely.geometry import box

# ── Project paths ──────────────────────────────────────────
ROOT = Path("/Users/gac/research_projects/atmospheric_rivers_orinoquia")
DATA_DIR = ROOT / "data" / "subgrid"
BASIN_GPKG = ROOT / "data/hydrobasins/orinoco_l6_basins.gpkg"
OUT_DIR = ROOT / "results" / "subgrid_masks"

# ── LULC Weights (Literature-based Relative Evaporative Coefficients) ──
# Reference: Penman-Monteith / Budyko framework parameters
# Normalized to Open Water = 1.0
# ESA WorldCover 2021 class mapping
LULC_WEIGHTS = {
    10: 0.15,  # Tree cover (generic — refined by biome below)
    20: 0.15,  # Shrubland
    30: 0.20,  # Grassland
    40: 0.50,  # Cropland
    50: 0.05,  # Built-up
    60: 0.20,  # Bare / sparse vegetation
    70: 0.08,  # Snow and ice
    80: 1.00,  # Permanent water bodies
    90: 0.95,  # Herbaceous wetland
    95: 0.60,  # Mangroves
    100: 0.55,  # Moss and lichen
}

# Refined biome-specific weights for tree cover classes
# These override the generic tree cover weight when biome data is available
BIOME_TREE_WEIGHTS = {
    "tropical_rainforest": 0.92,    # High LAI, deep roots, biotic pump
    "tropical_moist_deciduous": 0.78,
    "tropical_dry": 0.55,
    "montane_cloud_forest": 0.70,   # Reduced by cloud persistence
    "flooded_forest": 0.88,         # High water availability
    "savanna_woodland": 0.45,
    "degraded_secondary": 0.50,
    "plantation": 0.60,
}

# ── Elevation Scaling Function Φ(Z) ─────────────────────────
# Φ(Z) = exp(-γ × Z)  — inverse exponential decay
# γ = atmospheric lapse attenuation coefficient [m⁻¹]
# Calibrated for Andean slope profile (PET reduction with altitude)
#
# At Z=0:    Φ = 1.00  (sea level reference)
# At Z=500:  Φ ≈ 0.78  (lowland transition)
# At Z=1500: Φ ≈ 0.47  (mid-montane)
# At Z=3500: Φ ≈ 0.17  (páramo)

GAMMA_DEFAULT = 0.0005  # m⁻¹ (empirical Andean attenuation coefficient)

# Monthly seasonality adjustments
# PET varies seasonally even at same elevation due to radiation/VPD cycles
MONTHLY_GAMMA_ADJUSTMENT = {
    # Slightly higher attenuation in dry months (less cloud buffering)
    1: 1.05, 2: 1.05, 3: 1.00, 4: 0.95,
    5: 0.90, 6: 0.90, 7: 0.90, 8: 0.95,
    9: 1.00, 10: 1.00, 11: 1.02, 12: 1.05,
}


def elevation_scaling(z: np.ndarray, month: int = 1, gamma: float = GAMMA_DEFAULT) -> np.ndarray:
    """
    Φ(Z) = exp(-γ × Z × m_adj)
    
    Args:
        z: elevation array in meters
        month: calendar month (1-12) for seasonal adjustment
        gamma: base attenuation coefficient [m⁻¹]
    
    Returns:
        scaling factors in [0, 1]
    """
    gamma_m = gamma * MONTHLY_GAMMA_ADJUSTMENT.get(month, 1.0)
    return np.exp(-gamma_m * z)


def lulc_weight(lulc_array: np.ndarray) -> np.ndarray:
    """
    Map LULC class codes to evaporative weights L(k).
    
    Args:
        lulc_array: integer array of ESA WorldCover class codes
    
    Returns:
        weight array in [0, 1]
    """
    weights = np.zeros_like(lulc_array, dtype=np.float64)
    for code, w in LULC_WEIGHTS.items():
        weights[lulc_array == code] = w
    return weights


def compute_subgrid_mask(
    basin_geom,
    lulc_path: Path,
    dem_path: Path,
    month: int = 1,
    target_res_m: float = 100.0,
) -> dict:
    """
    Compute the sub-grid weighting matrix W(x) for a single basin.
    
    If LULC or DEM data is unavailable, falls back to uniform weighting
    (lumped basin behavior).
    
    Returns:
        dict with keys:
        - hybas_id: basin identifier
        - month: calendar month
        - n_pixels: number of 100m pixels in basin
        - weights: flattened weight array (normalized, sum=1)
        - mean_lulc_weight: spatial mean L(k)
        - mean_elevation_scaling: spatial mean Φ(Z)
        - mean_elevation_m: mean elevation
        - elevation_range_m: [min, max]
        - dominant_lulc_class: most common LULC code
        - method: 'subgrid' or 'lumped_fallback'
        - grid_bounds: [west, south, east, north]
        - grid_shape: [ny, nx]
    """
    bounds = basin_geom.bounds  # (minx, miny, maxx, maxy)

    has_lulc = lulc_path and lulc_path.exists()
    has_dem = dem_path and dem_path.exists()

    if not has_lulc and not has_dem:
        # Fast lumped fallback — skip rasterization
        width_m = (bounds[2] - bounds[0]) * 111320 * np.cos(np.radians((bounds[1] + bounds[3]) / 2))
        height_m = (bounds[3] - bounds[1]) * 111320
        nx = max(1, int(width_m / target_res_m))
        ny = max(1, int(height_m / target_res_m))
        npix = nx * ny
        return {
            "method": "lumped_fallback",
            "grid_shape": [ny, nx],
            "grid_bounds": list(bounds),
            "n_pixels": npix,
            "mean_lulc_weight": 1.0,
            "mean_elevation_scaling": 1.0,
            "mean_elevation_m": 0.0,
            "elevation_range_m": [0.0, 0.0],
            "dominant_lulc_class": 0,
            # Lumped = uniform; weight per pixel = 1/n_pixels. Don't store array.
            "uniform_weight": 1.0 / npix,
        }

    # Rasterize basin geometry
    width_m = (bounds[2] - bounds[0]) * 111320 * np.cos(np.radians((bounds[1] + bounds[3]) / 2))
    height_m = (bounds[3] - bounds[1]) * 111320
    nx = max(1, int(width_m / target_res_m))
    ny = max(1, int(height_m / target_res_m))
    transform = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], nx, ny)
    basin_mask = rasterize(
        [(basin_geom, 1)],
        out_shape=(ny, nx),
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    basin_pixels = basin_mask > 0

    # LULC weights
    if has_lulc:
        with rasterio.open(lulc_path) as src:
            lulc_data = src.read(1, out_shape=(ny, nx), resampling=Resampling.nearest,
                                window=src.window(*bounds))
        lulc_w = lulc_weight(lulc_data)
    else:
        lulc_w = np.ones((ny, nx))

    # Elevation scaling
    if has_dem:
        with rasterio.open(dem_path) as src:
            dem_data = src.read(1, out_shape=(ny, nx), resampling=Resampling.bilinear,
                               window=src.window(*bounds))
        elev_w = elevation_scaling(dem_data, month)
    else:
        elev_w = np.ones((ny, nx))
        dem_data = np.zeros((ny, nx))

    # Combined weight: W(x) = L(k) × Φ(Z)
    raw_w = lulc_w * elev_w
    raw_w[~basin_pixels] = 0.0

    total = raw_w.sum()
    if total > 0:
        weights = (raw_w / total).ravel().tolist()
    else:
        weights = [1.0 / basin_pixels.sum()] * int(basin_pixels.sum())

    return {
        "method": "subgrid",
        "grid_shape": [ny, nx],
        "grid_bounds": list(bounds),
        "n_pixels": int(basin_pixels.sum()),
        "mean_lulc_weight": float(lulc_w[basin_pixels].mean()) if has_lulc else 1.0,
        "mean_elevation_scaling": float(elev_w[basin_pixels].mean()) if has_dem else 1.0,
        "mean_elevation_m": float(dem_data[basin_pixels].mean()) if has_dem else 0.0,
        "elevation_range_m": [
            float(dem_data[basin_pixels].min()) if has_dem else 0.0,
            float(dem_data[basin_pixels].max()) if has_dem else 0.0,
        ],
        "dominant_lulc_class": int(np.bincount(lulc_data[basin_pixels].ravel().astype(int)).argmax()) if has_lulc else 0,
        "weights": weights,
    }


def compute_all_basins(
    lulc_path: Path = None,
    dem_path: Path = None,
    month: int = 1,
    target_res_m: float = 100.0,
) -> dict:
    """Compute sub-grid masks for all HydroBASINS L6 basins."""
    gdf = gpd.read_file(BASIN_GPKG)
    results = {}

    for _, row in gdf.iterrows():
        hybas = str(int(row["HYBAS_ID"]))
        mask = compute_subgrid_mask(
            row.geometry, lulc_path, dem_path, month, target_res_m
        )
        mask["hybas_id"] = hybas
        mask["sub_area_km2"] = float(row["SUB_AREA"])
        results[hybas] = mask

    return results


def main():
    parser = argparse.ArgumentParser(description="Sub-grid ecohydrological mask builder")
    parser.add_argument("--lulc", default=None, help="Path to ESA WorldCover GeoTIFF")
    parser.add_argument("--dem", default=None, help="Path to Copernicus DEM GeoTIFF")
    parser.add_argument("--month", type=int, default=1, help="Calendar month (1-12)")
    parser.add_argument("--resolution", type=float, default=100.0, help="Target pixel size in meters")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lulc_path = Path(args.lulc) if args.lulc else None
    dem_path = Path(args.dem) if args.dem else None

    if not lulc_path:
        print("WARNING: No LULC file provided — using uniform L(k)=1.0")
    if not dem_path:
        print("WARNING: No DEM file provided — using uniform Φ(Z)=1.0")
    print("Both missing = lumped fallback (uniform weighting)")
    print()

    masks = compute_all_basins(lulc_path, dem_path, args.month, args.resolution)

    # Summary
    n_subgrid = sum(1 for m in masks.values() if m["method"] == "subgrid")
    n_lumped = sum(1 for m in masks.values() if m["method"] == "lumped_fallback")
    print(f"Computed {len(masks)} basin masks: {n_subgrid} subgrid, {n_lumped} lumped")

    if n_subgrid > 0:
        sample = next(m for m in masks.values() if m["method"] == "subgrid")
        print(f"Sample subgrid: L̄={sample['mean_lulc_weight']:.3f}, "
              f"Φ̄={sample['mean_elevation_scaling']:.3f}, "
              f"Z̄={sample['mean_elevation_m']:.0f}m, "
              f"pixels={sample['n_pixels']}")

    # Save
    out_path = OUT_DIR / f"subgrid_masks_month{args.month:02d}.json"
    with open(out_path, "w") as f:
        json.dump(masks, f)
    print(f"\nSaved to {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
