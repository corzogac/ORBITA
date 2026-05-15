# ORBITA cloud storage architecture

Project: `rs-weather-data`

Primary ORBITA data bucket: `gs://rs-weather-data-orbit`

Existing weather-data lake detected: `gs://rs-weather-data-lake`

> Note: `rs-weather-data_ORBIT` is not a valid Google Cloud Storage bucket name because bucket names must be lowercase. The closest DNS-safe name is `rs-weather-data-orbit`. A lowercase underscore variant (`rs-weather-data_orbit`) is accepted by GCS but is less ideal for public/static access; use dashes.

## Recommendation

Use **Google Cloud Storage (GCS)** for data and **Firebase Hosting** only for the static web application shell.

Why:

- Firebase Hosting is excellent for `index.html`, JavaScript, CSS, logos, and small browser assets.
- GCS is cheaper and more appropriate for NetCDF/Zarr/Parquet trajectory data.
- Cloud Run / local Python / notebooks can read directly from GCS without repeatedly downloading full datasets.
- GCS lifecycle rules can move old raw data to colder storage automatically.

## Do not duplicate the same time/lat/lon repeatedly

Use a single canonical copy for each dataset and reference it everywhere.

### 1. Raw ERA5 archive: immutable monthly files

Keep the original CDS monthly NetCDF files exactly once:

```text
gs://rs-weather-data-orbit/raw/era5/south_america/pressure_levels/year=YYYY/month=MM/era5_sa_pl_<var>_YYYYMM.nc
gs://rs-weather-data-orbit/raw/era5/south_america/surface/year=YYYY/month=MM/era5_sa_sfc_instant_YYYYMM.nc
gs://rs-weather-data-orbit/raw/era5/south_america/surface/year=YYYY/month=MM/era5_sa_sfc_accum_YYYYMM.nc
```

These are the audit/reproducibility layer. They should be treated as write-once.

### 2. Analysis-optimized ERA5: consolidated Zarr by variable/time chunks

For fast trajectory computation, convert raw NetCDF to Zarr once, chunked by time and spatial blocks:

```text
gs://rs-weather-data-orbit/curated/era5/south_america/zarr/pressure_levels/<var>.zarr/
gs://rs-weather-data-orbit/curated/era5/south_america/zarr/surface/instant.zarr/
gs://rs-weather-data-orbit/curated/era5/south_america/zarr/surface/accum.zarr/
```

Recommended chunking for ORBITA:

- `time`: 31 days × 4 six-hourly steps = about 124 records, or smaller 7–14 day chunks if memory becomes tight.
- `pressure_level`: all levels for one variable when doing vertical interpolation, or chunks of 8–12 levels for 3D runs.
- `latitude` / `longitude`: 128×128 or 256×256 chunks.
- compression: Zarr with Blosc/Zstd if available; otherwise NetCDF deflate for archival files.

This avoids many small object reads and avoids duplicating coordinates inside many per-basin products.

### 3. Trajectory outputs: Parquet, partitioned by run/month/arrival basin

Store particle results once as columnar Parquet:

```text
gs://rs-weather-data-orbit/trajectories/prototype_2d_rk4/year=2023/month=01/part-000.parquet
gs://rs-weather-data-orbit/trajectories/production_3d_rk4_v1/year=YYYY/month=MM/arrival_hybas_id=<ID>/part-000.parquet
```

Preferred columns:

```text
run_id, trajectory_id, release_time_utc, valid_time_utc, hour_back,
lat, lon, pressure_hpa, u_ms, v_ms, q_kgkg,
arrival_hybas_id, source_hybas_id, source_tag,
uptake_kg, uptake_volume_m3, displacement_h, source_mode
```

Why Parquet:

- fast reads for selected months/basins;
- strong compression;
- schema evolution is manageable;
- can be queried by DuckDB, pandas, Spark, BigQuery external tables later.

### 4. Monthly basin aggregates: small, web-ready products

The browser platform should not load raw particle files. Build compact monthly products:

```text
gs://rs-weather-data-orbit/aggregated/monthly_contributions/version=v1/year=YYYY/month=MM/contributions.parquet
gs://rs-weather-data-orbit/aggregated/monthly_contributions/version=v1/contributions_browser.csv
gs://rs-weather-data-orbit/platform/orbita/assets/...
```

Core monthly aggregate schema:

```text
arrival_hybas_id, source_hybas_id, year, month,
evap_contribution_kg, evap_contribution_m3, pct_of_arrival_total,
mean_displacement_h, p10_displacement_h, p90_displacement_h,
n_particles, n_source_contacts, method_version
```

## Suggested bucket layout

```text
gs://rs-weather-data-orbit/
  raw/
    era5/
      south_america/
        pressure_levels/year=YYYY/month=MM/*.nc
        surface/year=YYYY/month=MM/*.nc
    hydrobasins/
      level=05/*
      level=06/*
  curated/
    era5/
      south_america/zarr/...
    hydrobasins/
      orinoco_l6_basins.gpkg
  trajectories/
    prototype_2d_rk4/year=YYYY/month=MM/*.parquet
    production_3d_rk4_v1/year=YYYY/month=MM/arrival_hybas_id=*/part-*.parquet
  aggregated/
    monthly_contributions/version=v1/year=YYYY/month=MM/*.parquet
  platform/
    orbita/
      index.html
      assets/*.csv
      assets/*.json
      assets/*.geojson
  manifests/
    era5_inventory.json
    sync_manifest.json
```

## Access pattern

- Local and Cloud Run jobs read with `gcsfs` using `gs://...` paths.
- Static ORBITA/Firebase reads only small public or signed platform assets from `platform/orbita/` and `aggregated/`.
- Raw/curated ERA5 should stay private.
- If public demo access is needed, expose only `platform/orbita/**` and maybe selected `aggregated/**`, not raw ERA5.

## Cost controls

1. Use a regional bucket close to compute, preferably `us-central1` if Cloud Run/Firebase/compute are there.
2. Enable lifecycle rules:
   - keep `raw/` in Standard while actively computing;
   - move old raw files to Nearline/Coldline after 90–180 days if not used;
   - keep `platform/` and `aggregated/` in Standard for fast web access.
3. Avoid requester-pays unless collaborators need isolated billing.
4. Avoid storing both CSV and Parquet for large tables. Use Parquet as canonical; CSV only for small browser extracts.
5. Use `gsutil rsync`/checksums to prevent duplicate uploads.

## Firebase Hosting role

Use Firebase Hosting for:

```text
/index.html
/assets/app.js
/assets/styles.css
/assets/logo.svg
```

Do not use Firebase Hosting for:

- multi-GB ERA5 NetCDF;
- large trajectory Parquet;
- repeated model intermediates.

Firebase can point the app to GCS-hosted small assets or to a Cloud Run API that serves filtered data.

## Immediate ORBITA convention

Local canonical raw data remains at:

```text
/Volumes/GC_SDD1/ncdata/era5_sa/
```

Cloud canonical mirror becomes:

```text
gs://rs-weather-data-orbit/raw/era5/south_america/
```

Processed platform mirror becomes:

```text
gs://rs-weather-data-orbit/platform/orbita/
```
