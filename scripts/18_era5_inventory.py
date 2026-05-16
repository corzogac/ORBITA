#!/usr/bin/env python3
"""
ERA5 Data Inventory — Local + GCS
=================================
Scans local storage and GCS for ERA5 NetCDF files, reporting:
  - Years, months, variables available
  - File sizes and completeness (pressure-level: 6 vars, surface: 2 kinds)
  - Coverage gaps
  - Local vs remote sync status

Usage:
  python scripts/18_era5_inventory.py                    # local only
  python scripts/18_era5_inventory.py --gcs              # local + GCS
  python scripts/18_era5_inventory.py --local-root /other/path  # custom path
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PL_VARS = ["u", "v", "q", "w", "t", "z"]
SFC_KINDS = ["instant", "accum"]
DEFAULT_LOCAL = Path("/Volumes/GC_SDD1/ncdata/era5_sa")
GCS_BUCKET = "gs://rs-weather-data-orbit/raw/era5/south_america"


def scan_local(root: Path) -> dict:
    """Scan local ERA5 directory tree. Returns per-month inventory."""
    inventory = defaultdict(lambda: {"pl": {}, "sfc": {}, "size_bytes": 0})

    for pl_file in root.glob("pressure_levels/*/*.nc"):
        fname = pl_file.name  # era5_sa_pl_{var}_YYYYMM.nc
        parts = fname.replace(".nc", "").split("_")
        if len(parts) < 5:
            continue
        var = parts[3]
        ym = parts[4]  # YYYYMM
        size = pl_file.stat().st_size
        if size > 1e6:  # skip tiny/incomplete files
            inventory[ym]["pl"][var] = size
            inventory[ym]["size_bytes"] += size

    for sfc_file in root.glob("surface/*/*.nc"):
        fname = sfc_file.name  # era5_sa_sfc_{kind}_YYYYMM.nc
        parts = fname.replace(".nc", "").split("_")
        if len(parts) < 5:
            continue
        kind = parts[3]  # instant or accum
        ym = parts[4]
        size = sfc_file.stat().st_size
        if size > 1e6:
            inventory[ym]["sfc"][kind] = size
            inventory[ym]["size_bytes"] += size

    return dict(inventory)


def scan_gcs() -> dict:
    """Scan GCS bucket for ERA5 NetCDF files."""
    try:
        result = subprocess.run(
            ["gsutil", "ls", "-r", f"{GCS_BUCKET}/**"],
            capture_output=True, text=True, timeout=30
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"error": "gsutil not available or timed out"}

    inventory = defaultdict(lambda: {"pl": {}, "sfc": {}})
    for line in result.stdout.strip().split("\n"):
        if not line.endswith(".nc"):
            continue
        fname = line.rstrip("/").split("/")[-1]
        parts = fname.replace(".nc", "").split("_")
        if len(parts) < 5:
            continue
        var_or_kind = parts[3]
        ym = parts[4]
        if var_or_kind in PL_VARS:
            inventory[ym]["pl"][var_or_kind] = "remote"
        elif var_or_kind in SFC_KINDS:
            inventory[ym]["sfc"][var_or_kind] = "remote"

    return dict(inventory)


def print_table(local: dict, gcs, title: str, years: list):
    """Print a formatted inventory table."""
    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}")
    print(f"{'Month':>8}  {'PL vars':>24}  {'SFC kinds':>16}  {'Size':>10}  {'Status':>15}")
    print(f"{'-'*8}  {'-'*24}  {'-'*16}  {'-'*10}  {'-'*15}")

    total_gb = 0
    for ym in sorted(local.keys()):
        if local:
            pl = local.get(ym, {}).get("pl", {})
            sfc = local.get(ym, {}).get("sfc", {})
            size = local.get(ym, {}).get("size_bytes", 0)
            gb = size / 1e9
            total_gb += gb
            pl_str = ",".join(sorted(pl.keys())) if pl else "—"
            sfc_str = ",".join(sorted(sfc.keys())) if sfc else "—"
            pl_ok = len(pl) == 6
            sfc_ok = len(sfc) == 2
            if pl_ok and sfc_ok:
                status = "✓ COMPLETE"
            elif pl or sfc:
                n = len(pl) + len(sfc)
                status = f"{n}/8 files"
            else:
                status = "empty"
            print(f"  {ym}  {pl_str:>24}  {sfc_str:>16}  {gb:>8.1f}G  {status:>15}")

    print(f"  {'─'*8}  {'─'*24}  {'─'*16}  {'─'*10}  {'─'*15}")
    print(f"  {'TOTAL':>8}  {'':>24}  {'':>16}  {total_gb:>8.1f}G")

    # Summary stats
    complete = sum(1 for ym, d in local.items()
                   if len(d.get("pl", {})) == 6 and len(d.get("sfc", {})) == 2)
    total_months = len(local)
    print(f"\n  {complete}/{total_months} months complete (8/8 files)")
    if not complete:
        incomplete = [(ym, 8 - len(local[ym].get("pl", {})) - len(local[ym].get("sfc", {})))
                      for ym in local if len(local[ym].get("pl", {})) < 6 or len(local[ym].get("sfc", {})) < 2]
        print(f"  Incomplete months: {', '.join(f'{ym}(-{n})' for ym, n in incomplete[:10])}")

    # GCS comparison
    if gcs and "error" not in gcs:
        local_only = set(local.keys()) - set(gcs.keys())
        gcs_only = set(gcs.keys()) - set(local.keys())
        in_sync = set(local.keys()) & set(gcs.keys())
        if local_only:
            print(f"\n  ⚠ Local only (not on GCS): {', '.join(sorted(local_only)[:15])}")
        if gcs_only:
            print(f"  ⚠ GCS only (not local): {', '.join(sorted(gcs_only)[:15])}")
        print(f"  ✓ In sync (local+GCS): {len(in_sync)} months")


def main():
    parser = argparse.ArgumentParser(description="ERA5 data inventory")
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL,
                        help=f"Local ERA5 root (default: {DEFAULT_LOCAL})")
    parser.add_argument("--gcs", action="store_true", help="Also scan GCS bucket")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    args = parser.parse_args()

    local = scan_local(args.local_root) if args.local_root.exists() else {}
    gcs = scan_gcs() if args.gcs else None

    if args.json:
        output = {"local": local}
        if gcs:
            output["gcs"] = gcs
        print(json.dumps(output, indent=2))
    else:
        years = sorted(set(ym[:4] for ym in local))
        print(f"Local root: {args.local_root}")
        print(f"Years found: {', '.join(years) if years else 'none'}")
        print(f"Total months: {len(local)}")
        print_table(local, gcs, "ERA5 INVENTORY", years)

        # Variable coverage matrix
        print(f"\n{'='*90}")
        print(f"  VARIABLE COVERAGE (✓ = at least one month)")
        print(f"{'='*90}")
        all_vars = PL_VARS + SFC_KINDS
        for v in all_vars:
            months_with = sum(1 for ym, d in local.items()
                            if v in d.get("pl", {}) or v in d.get("sfc", {}))
            print(f"  {v:>8}: {months_with}/{len(local)} months")


if __name__ == "__main__":
    main()
