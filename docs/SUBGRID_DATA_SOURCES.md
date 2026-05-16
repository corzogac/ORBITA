# Sub-Grid Data Sources

## Required Datasets

### 1. ESA WorldCover 2021 v200 (10m Land Use / Land Cover)

**Download URL:** https://worldcover2021.esa.int/downloader

Select "South America" tile (ESA_WorldCover_10m_2021_v200_SouthAmerica_Map.tif)

Alternative: AWS S3 bucket (if accessible)
```
aws s3 cp s3://esa-worldcover/v200/2021/map/ESA_WorldCover_10m_2021_v200_SouthAmerica_Map.tif \
  data/subgrid/ --no-sign-request
```

**Size:** ~8 GB for South America tile
**Place at:** `data/subgrid/ESA_WorldCover_10m_2021_v200_SouthAmerica_Map.tif`

**LULC Classes used in mask:**

| Code | Class | Evaporative Weight L(k) |
|------|-------|------------------------|
| 10 | Tree cover | 0.15 (refined by biome) |
| 20 | Shrubland | 0.15 |
| 30 | Grassland | 0.20 |
| 40 | Cropland | 0.50 |
| 50 | Built-up | 0.05 |
| 60 | Bare / sparse vegetation | 0.20 |
| 70 | Snow and ice | 0.08 |
| 80 | Permanent water bodies | 1.00 |
| 90 | Herbaceous wetland | 0.95 |
| 95 | Mangroves | 0.60 |
| 100 | Moss and lichen | 0.55 |

### 2. Copernicus DEM GLO-30 (30m Elevation)

**Download URL:** https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/

Use `data/subgrid/download_copernicus_dem.sh` for automated tile download.
The Orinoquia region spans approximately Copernicus DEM tiles:
- N10W075, N10W080, N05W070, N05W075, N00W070, N00W075, S05W070

**Place at:** `data/subgrid/copernicus_dem_orinoquia.tif` (merged/mosaiced)

**Size:** ~200 MB for the merged Orinoquia region

## Quick Download Commands

```bash
# ESA WorldCover (manual download from website)
open https://worldcover2021.esa.int/downloader

# Copernicus DEM (using AWS CLI)
pip install awscli
mkdir -p data/subgrid/dem_tiles
for tile in N10W075 N10W080 N05W070 N05W075 N00W070 N00W075 S05W070; do
  aws s3 cp "s3://copernicus-dem-30m/${tile}/${tile}.tif" data/subgrid/dem_tiles/ --no-sign-request
done
```

## Test with Synthetic Data

The mask builder works without real data (lumped fallback).
To test with synthetic data:
```bash
python scripts/17_subgrid_attribution_mask.py --month 1
```

To test with real data:
```bash
python scripts/17_subgrid_attribution_mask.py \
  --lulc data/subgrid/ESA_WorldCover_10m_2021_v200_SouthAmerica_Map.tif \
  --dem data/subgrid/copernicus_dem_orinoquia.tif \
  --month 1
```
