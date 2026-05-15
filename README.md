# ORBITA – Orinoquia–Andes Basin Integrated Trajectory Analysis

**Water vapor transport from Orinoquia to the Colombian Andes** using ERA5 reanalysis, HydroBASINS, and Lagrangian back-trajectories.

The live prototype platform is generated as a static browser app under:

```text
results/trajectory_platform/index.html
```

## Current architecture

- **Code/docs/platform:** GitHub repository `https://github.com/corzogac/ORBITA.git`
- **Local raw ERA5 archive:** `/Volumes/GC_SDD1/ncdata/era5_sa/`
- **Primary cloud data bucket:** `gs://rs-weather-data-orbit`
- **Existing weather-data lake:** `gs://rs-weather-data-lake`
- **Platform assets in GCS:** `gs://rs-weather-data-orbit/platform/orbita/`

See:

```text
docs/DESIGN.md
docs/CLOUD_STORAGE_ARCHITECTURE.md
docs/TRAJECTORY_PLATFORM_ADDENDUM.md
```

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Prepare HydroBASINS L6 corridor polygons
python scripts/07_prepare_hydrobasins_l6.py

# Download ERA5 by safe monthly/variable chunks
python scripts/01_download_era5.py --year 2023

# Generate prototype 2D RK4 trajectory months from all complete u/v/q downloads
python scripts/09_generate_available_2023_platform_ensemble.py

# Rebuild browser-ready ORBITA assets
python scripts/05_build_trajectory_platform_assets.py

# Serve locally
cd results/trajectory_platform
python3 -m http.server 8788
```

## Cloud sync

Use the sync helpers instead of manually copying files:

```bash
# Create/check bucket
./scripts/10_sync_orbita_gcs.sh ensure-bucket

# Sync small platform assets and processed trajectory outputs
./scripts/10_sync_orbita_gcs.sh sync-processed

# Upload only complete raw ERA5 monthly files, avoiding active partial downloads
python scripts/11_sync_complete_era5_months_to_gcs.py --years 2023

# Inventory
./scripts/10_sync_orbita_gcs.sh inventory
```

## Data layout in GCS

```text
gs://rs-weather-data-orbit/
  raw/era5/south_america/pressure_levels/year=YYYY/month=MM/*.nc
  raw/era5/south_america/surface/year=YYYY/month=MM/*.nc
  curated/era5/south_america/zarr/...
  trajectories/prototype_2d_rk4/...
  trajectories/production_3d_rk4_v1/...
  aggregated/monthly_contributions/...
  platform/orbita/...
  manifests/...
```

## Scientific status

The current platform uses a **2D fixed-pressure RK4 prototype** for path visualization and contact-frequency proxies. Physical evaporation-volume attribution is pending the production 3D RK4 + moisture uptake engine.

Current prototype variables:

- ERA5 `u`, `v`, `q` at 850/700/500 hPa
- 6-hour releases
- 72-hour backward trajectory window
- HydroBASINS L6 arrival-basin filtering

## Git/data boundary

GitHub stores code, documentation, configs, small browser assets, and JSON summaries. It intentionally excludes:

- raw ERA5 NetCDF/GRIB/Zarr files;
- heavy trajectory CSV/Parquet tables;
- virtual environments;
- credentials and secrets.

Use GCS for canonical data products.
