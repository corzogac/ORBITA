#!/usr/bin/env python3
"""Build analysis-optimized ORBITA ERA5 Zarr stores from local NetCDF files.

This is the fast-access layer for trajectory computation. The raw NetCDF files
remain the audit archive; the Zarr store is chunked for cloud/local reads with
xarray+dask and can be synced to GCS.

Examples:
  python scripts/13_build_era5_zarr_store.py --year 2023 --kind pressure --var u
  python scripts/13_build_era5_zarr_store.py --year 2023 --kind surface --surface-kind instant
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
ERA5_ROOT = Path("/Volumes/GC_SDD1/ncdata/era5_sa")
LOCAL_ZARR = ROOT / "results" / "zarr"
BUCKET = "gs://rs-weather-data-orbit"


def sh(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def pressure_files(year: int, var: str) -> list[Path]:
    return sorted((ERA5_ROOT / "pressure_levels" / str(year)).glob(f"era5_sa_pl_{var}_{year}[0-9][0-9].nc"))


def surface_files(year: int, surface_kind: str) -> list[Path]:
    return sorted((ERA5_ROOT / "surface" / str(year)).glob(f"era5_sa_sfc_{surface_kind}_{year}[0-9][0-9].nc"))


def normalize(ds: xr.Dataset) -> xr.Dataset:
    if "latitude" in ds.coords and ds.latitude.values[0] > ds.latitude.values[-1]:
        ds = ds.sortby("latitude")
    if "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    return ds


def build(files: list[Path], out: Path, mode: str) -> None:
    if not files:
        raise FileNotFoundError("No source NetCDF files found")
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Opening {len(files)} files")
    ds = xr.open_mfdataset(
        [str(p) for p in files],
        combine="by_coords",
        chunks={"valid_time": 124, "time": 124, "pressure_level": 8, "latitude": 128, "longitude": 128},
        parallel=False,
        engine="netcdf4",
    )
    ds = normalize(ds)
    chunks = {"time": 124, "latitude": 128, "longitude": 128}
    if "pressure_level" in ds.dims:
        chunks["pressure_level"] = 8
    ds = ds.chunk(chunks)
    print(ds)
    ds.to_zarr(out, mode=mode, consolidated=True)
    print(f"Wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--kind", choices=["pressure", "surface"], required=True)
    ap.add_argument("--var", help="Pressure-level short variable: u, v, q, w, t, z")
    ap.add_argument("--surface-kind", choices=["instant", "accum"], default="instant")
    ap.add_argument("--sync-gcs", action="store_true")
    ap.add_argument("--mode", default="w", choices=["w", "w-", "a"])
    args = ap.parse_args()

    if args.kind == "pressure":
        if not args.var:
            raise SystemExit("--var is required for --kind pressure")
        files = pressure_files(args.year, args.var)
        out = LOCAL_ZARR / "era5" / "south_america" / "pressure_levels" / f"var={args.var}" / f"year={args.year}.zarr"
        gcs_dest = f"{BUCKET}/curated/era5/south_america/zarr/pressure_levels/var={args.var}/year={args.year}.zarr"
    else:
        files = surface_files(args.year, args.surface_kind)
        out = LOCAL_ZARR / "era5" / "south_america" / "surface" / f"kind={args.surface_kind}" / f"year={args.year}.zarr"
        gcs_dest = f"{BUCKET}/curated/era5/south_america/zarr/surface/kind={args.surface_kind}/year={args.year}.zarr"

    build(files, out, args.mode)
    if args.sync_gcs:
        sh(["gsutil", "-m", "rsync", "-r", str(out), gcs_dest])


if __name__ == "__main__":
    main()
