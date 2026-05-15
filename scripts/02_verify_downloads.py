#!/usr/bin/env python3
"""Verify ERA5 files for the atmospheric rivers project."""

import json
from pathlib import Path

import xarray as xr
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "era5_variables.yaml"))
    base = Path(cfg["storage"]["base_path"])

    files = sorted([p for p in base.rglob("*.nc") if not p.name.startswith("._")])
    print(f"ERA5 base: {base}")
    print(f"NetCDF files: {len(files)}")

    total = 0
    for p in files:
        size = p.stat().st_size
        total += size
        rel = p.relative_to(base)
        print(f"\n{rel} ({size/1e6:.1f} MB)")
        try:
            ds = xr.open_dataset(p, engine="netcdf4")
            print(f"  dims: {dict(ds.dims)}")
            print(f"  vars: {list(ds.data_vars)[:10]}")
            if "valid_time" in ds.coords:
                print(f"  time steps: {ds.sizes.get('valid_time')}")
            elif "time" in ds.coords:
                print(f"  time steps: {ds.sizes.get('time')}")
            ds.close()
        except Exception as e:
            print(f"  ERROR opening file: {e}")

    print(f"\nTotal size: {total/1e9:.2f} GB")


if __name__ == "__main__":
    main()
