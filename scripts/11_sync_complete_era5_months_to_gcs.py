#!/usr/bin/env python3
"""Upload only complete ORBITA ERA5 monthly files to GCS.

This avoids copying partially downloaded active files. A month is considered
complete when all six pressure-level variables (u, v, q, w, t, z) and both
surface files (instant, accum) exist and pass a minimum-size check.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ERA5_ROOT = Path("/Volumes/GC_SDD1/ncdata/era5_sa")
BUCKET = "gs://rs-weather-data-orbit"
PRESSURE_VARS = ["u", "v", "q", "w", "t", "z"]
SURFACE_KINDS = ["instant", "accum"]
MIN_SIZE = 1_000_000


def sh(cmd: list[str], dry_run: bool = False) -> None:
    print("+", " ".join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, check=True)


def complete_month(year: int, month: int) -> tuple[bool, list[Path]]:
    files: list[Path] = []
    for var in PRESSURE_VARS:
        files.append(ERA5_ROOT / "pressure_levels" / str(year) / f"era5_sa_pl_{var}_{year}{month:02d}.nc")
    for kind in SURFACE_KINDS:
        files.append(ERA5_ROOT / "surface" / str(year) / f"era5_sa_sfc_{kind}_{year}{month:02d}.nc")
    ok = all(p.exists() and p.stat().st_size >= MIN_SIZE for p in files)
    return ok, files


def object_path(local: Path, year: int, month: int) -> str:
    rel = local.relative_to(ERA5_ROOT)
    if rel.parts[0] == "pressure_levels":
        # pressure_levels/YYYY/file.nc -> raw/era5/.../pressure_levels/year=YYYY/month=MM/file.nc
        return f"{BUCKET}/raw/era5/south_america/pressure_levels/year={year}/month={month:02d}/{local.name}"
    if rel.parts[0] == "surface":
        return f"{BUCKET}/raw/era5/south_america/surface/year={year}/month={month:02d}/{local.name}"
    raise ValueError(local)


def build_inventory(years: list[int]) -> dict:
    months = []
    total_bytes = 0
    for year in years:
        for month in range(1, 13):
            ok, files = complete_month(year, month)
            if ok:
                month_bytes = sum(p.stat().st_size for p in files)
                total_bytes += month_bytes
                months.append(
                    {
                        "year": year,
                        "month": month,
                        "files": len(files),
                        "bytes": month_bytes,
                        "objects": [object_path(p, year, month) for p in files],
                    }
                )
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "era5_root": str(ERA5_ROOT),
        "bucket": BUCKET,
        "complete_months": months,
        "n_complete_months": len(months),
        "total_bytes": total_bytes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2023", help="Comma-separated years to scan, e.g. 2023 or 2010,2011")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-incomplete", action="store_true", help="Dangerous: upload available files even if month incomplete")
    args = ap.parse_args()

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    uploaded = []
    skipped = []
    for year in years:
        for month in range(1, 13):
            ok, files = complete_month(year, month)
            existing_files = [p for p in files if p.exists() and p.stat().st_size >= MIN_SIZE]
            if not ok and not args.include_incomplete:
                if existing_files:
                    skipped.append(f"{year}-{month:02d} incomplete ({len(existing_files)}/{len(files)} files)")
                continue
            for local in (files if ok else existing_files):
                dest = object_path(local, year, month)
                sh(["gsutil", "-m", "cp", "-n", str(local), dest], dry_run=args.dry_run)
                uploaded.append(dest)

    inventory = build_inventory(years)
    manifest_path = Path("/tmp/orbita_era5_complete_months_inventory.json")
    manifest_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    sh(["gsutil", "cp", str(manifest_path), f"{BUCKET}/manifests/era5_complete_months_inventory.json"], dry_run=args.dry_run)

    print(json.dumps({
        "years": years,
        "uploaded_or_existing_objects": len(uploaded),
        "skipped": skipped,
        "complete_months": [f"{m['year']}-{m['month']:02d}" for m in inventory["complete_months"]],
        "total_gib_complete": round(inventory["total_bytes"] / (1024**3), 2),
        "dry_run": args.dry_run,
    }, indent=2))


if __name__ == "__main__":
    main()
