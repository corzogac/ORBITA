#!/usr/bin/env python3
"""Download ERA5 data for South America domain via CDS API.

Downloads pressure-level and surface variables for the Lagrangian
back-trajectory analysis of water vapor transport.

Usage:
    python scripts/01_download_era5.py --year 2023 --month 1           # single month
    python scripts/01_download_era5.py --year 2023                     # full year
    python scripts/01_download_era5.py --start 2020 --end 2024         # range
    python scripts/01_download_era5.py --test                          # test month (2023-01)
"""

import argparse
import json
import logging
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import cdsapi
import yaml

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config():
    """Load ERA5 variable configuration."""
    config_path = PROJECT_ROOT / "config" / "era5_variables.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def month_range(start_year, start_month, end_year, end_month):
    """Generate (year, month) tuples over a range."""
    current = datetime(start_year, start_month, 1)
    end = datetime(end_year, end_month, 1)
    while current <= end:
        yield (current.year, current.month)
        # advance one month
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)


def download_pressure_levels(client, cfg, year, month, force=False):
    """Download pressure-level variables for one month.

    CDS rejects one huge request for all variables × 37 levels × full South
    America × full month. We therefore download one variable per monthly file.
    This is more restartable and keeps each request below CDS cost limits.
    """
    domain = cfg["domain"]
    levels = cfg["pressure_levels"]
    variables = cfg["pressure_level_variables"]
    dataset = cfg["datasets"]["pressure_levels"]
    storage = cfg["storage"]

    out_dir = Path(storage["base_path"]) / storage["pressure_subdir"] / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Calculate days in month
    if month == 12:
        last_day = 31
    else:
        last_day = (datetime(year, month + 1, 1) - timedelta(days=1)).day

    downloaded_files = []

    for variable in variables:
        short = {
            "u_component_of_wind": "u",
            "v_component_of_wind": "v",
            "specific_humidity": "q",
            "temperature": "t",
            "geopotential": "z",
            "vertical_velocity": "w",
        }.get(variable, variable)

        out_file = out_dir / f"era5_sa_pl_{short}_{year}{month:02d}.nc"

        if not force and out_file.exists() and out_file.stat().st_size > 10_000_000:
            logger.info(f"  PL {short} {year}-{month:02d}: already exists ({out_file.stat().st_size / 1e6:.0f} MB), skipping")
            downloaded_files.append(out_file)
            continue

        request = {
            "product_type": ["reanalysis"],
            "variable": [variable],
            "pressure_level": [str(p) for p in levels],
            "year": [str(year)],
            "month": [f"{month:02d}"],
            "day": [f"{d:02d}" for d in range(1, last_day + 1)],
            "time": ["00:00", "06:00", "12:00", "18:00"],
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": [domain["north"], domain["west"], domain["south"], domain["east"]],
        }

        logger.info(f"  PL {short} {year}-{month:02d}: downloading (1 var, {len(levels)} levels, {last_day} days)...")
        t0 = time.time()

        try:
            client.retrieve(dataset, request, str(out_file))
            elapsed = time.time() - t0
            size_mb = out_file.stat().st_size / 1e6
            logger.info(f"  PL {short} {year}-{month:02d}: done ({size_mb:.0f} MB in {elapsed:.0f}s)")
            downloaded_files.append(out_file)
        except Exception as e:
            logger.error(f"  PL {short} {year}-{month:02d}: FAILED - {e}")
            if out_file.exists():
                out_file.unlink()
            # Continue with other variables; one failed variable should not
            # prevent downloading the rest of the test/month.
            continue

    if not downloaded_files:
        raise RuntimeError(f"No pressure-level files downloaded for {year}-{month:02d}")

    return downloaded_files


def download_surface(client, cfg, year, month, force=False):
    """Download surface/single-level variables for one month."""
    domain = cfg["domain"]
    variables = cfg["surface_variables"]
    dataset = cfg["datasets"]["surface"]
    storage = cfg["storage"]

    out_dir = Path(storage["base_path"]) / storage["surface_subdir"] / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)

    if month == 12:
        last_day = 31
    else:
        last_day = (datetime(year, month + 1, 1) - timedelta(days=1)).day

    out_file = out_dir / f"era5_sa_sfc_{year}{month:02d}.nc"
    instant_file = out_dir / f"era5_sa_sfc_instant_{year}{month:02d}.nc"
    accum_file = out_dir / f"era5_sa_sfc_accum_{year}{month:02d}.nc"

    if not force:
        if instant_file.exists() and accum_file.exists() and instant_file.stat().st_size > 1_000_000 and accum_file.stat().st_size > 1_000_000:
            logger.info(
                f"  SFC {year}-{month:02d}: extracted instant+accum files already exist "
                f"({(instant_file.stat().st_size + accum_file.stat().st_size) / 1e6:.0f} MB), skipping"
            )
            return [instant_file, accum_file]
        if out_file.exists() and out_file.stat().st_size > 1_000_000 and not zipfile.is_zipfile(out_file):
            logger.info(f"  SFC {year}-{month:02d}: already exists ({out_file.stat().st_size / 1e6:.0f} MB), skipping")
            return out_file

    request = {
        "product_type": ["reanalysis"],
        "variable": variables,
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, last_day + 1)],
        "time": ["00:00", "06:00", "12:00", "18:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [domain["north"], domain["west"], domain["south"], domain["east"]],
    }

    logger.info(f"  SFC {year}-{month:02d}: downloading ({len(variables)} vars, {last_day} days)...")
    t0 = time.time()

    try:
        client.retrieve(dataset, request, str(out_file))
        elapsed = time.time() - t0
        size_mb = out_file.stat().st_size / 1e6
        logger.info(f"  SFC {year}-{month:02d}: done ({size_mb:.0f} MB in {elapsed:.0f}s)")

        # CDS can return a ZIP container even when NetCDF is requested,
        # especially when variables mix instantaneous and accumulated step
        # types. Detect and extract to stable NetCDF names.
        if zipfile.is_zipfile(out_file):
            logger.info(f"  SFC {year}-{month:02d}: CDS returned ZIP; extracting NetCDF members")
            extracted = []
            with zipfile.ZipFile(out_file, "r") as zf:
                for member in zf.namelist():
                    if not member.endswith(".nc"):
                        continue
                    kind = "instant" if "instant" in member else "accum" if "accum" in member else "part"
                    target = out_dir / f"era5_sa_sfc_{kind}_{year}{month:02d}.nc"
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    extracted.append(target)
                    logger.info(f"    extracted {member} -> {target.name} ({target.stat().st_size/1e6:.0f} MB)")

            archive = out_file.with_suffix(".zip")
            if archive.exists():
                archive.unlink()
            out_file.rename(archive)
            return extracted

        return out_file
    except Exception as e:
        logger.error(f"  SFC {year}-{month:02d}: FAILED - {e}")
        if out_file.exists():
            out_file.unlink()
        raise


def write_manifest(cfg, downloaded_files=None):
    """Write a manifest of all ERA5 NetCDF files currently in storage.

    Earlier versions only recorded files from the latest run, which caused the
    manifest to appear to lose pressure-level files after a surface-only run.
    The manifest is now a true inventory of the storage tree.
    """
    storage = cfg["storage"]
    base_path = Path(storage["base_path"])
    manifest_path = base_path / "manifest.json"

    all_files = sorted(p for p in base_path.rglob("*.nc") if not p.name.startswith("._"))
    downloaded_set = {Path(p).resolve() for p in (downloaded_files or [])}

    manifest = {
        "updated": datetime.now().isoformat(),
        "domain": cfg["domain"],
        "pressure_levels": cfg["pressure_levels"],
        "pressure_level_variables": cfg["pressure_level_variables"],
        "surface_variables": cfg["surface_variables"],
        "files": []
    }

    total_size = 0
    for fpath in all_files:
        size = fpath.stat().st_size
        total_size += size
        manifest["files"].append({
            "path": str(fpath.relative_to(base_path)),
            "size_bytes": size,
            "size_gb": round(size / 1e9, 3),
            "downloaded_this_run": fpath.resolve() in downloaded_set,
        })

    manifest["total_files"] = len(manifest["files"])
    manifest["total_size_gb"] = round(total_size / 1e9, 2)

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Manifest written: {manifest_path} ({manifest['total_files']} files, {manifest['total_size_gb']} GB)")


def main():
    parser = argparse.ArgumentParser(description="Download ERA5 data for South America")
    parser.add_argument("--year", type=int, help="Single year to download")
    parser.add_argument("--month", type=int, help="Single month (1-12), requires --year")
    parser.add_argument("--start", type=int, help="Start year for range")
    parser.add_argument("--end", type=int, help="End year for range")
    parser.add_argument("--test", action="store_true", help="Download test month (2023-01)")
    parser.add_argument("--surface-only", action="store_true", help="Only download surface variables")
    parser.add_argument("--pressure-only", action="store_true", help="Only download pressure-level variables")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--no-manifest", action="store_true", help="Skip writing manifest")
    args = parser.parse_args()

    # Determine what to download
    if args.test:
        year, month = 2023, 1
        logger.info("TEST MODE: downloading 2023-01 only")
    elif args.year and args.month:
        year, month = args.year, args.month
        end_year, end_month = year, month
    elif args.year:
        start_year, start_month = args.year, 1
        end_year, end_month = args.year, 12
    elif args.start and args.end:
        start_year, start_month = args.start, 1
        end_year, end_month = args.end, 12
    else:
        parser.error("Specify --test, --year [--month], or --start --end")

    cfg = load_config()

    # Load CDS API client
    logger.info("Initializing CDS API client...")
    client = cdsapi.Client()

    # Generate month list
    if args.test or (args.year and args.month):
        months = [(year, month)]
    else:
        months = list(month_range(start_year, start_month, end_year, end_month))

    logger.info(f"Will download {len(months)} month(s)")
    
    downloaded = []

    for yr, mo in months:
        logger.info(f"--- Processing {yr}-{mo:02d} ---")
        
        if not args.surface_only:
            try:
                f = download_pressure_levels(client, cfg, yr, mo, force=args.force)
                if f:
                    if isinstance(f, list):
                        downloaded.extend(f)
                    else:
                        downloaded.append(f)
            except Exception:
                logger.error(f"Pressure-level download failed for {yr}-{mo:02d}, continuing...")
        
        if not args.pressure_only:
            try:
                f = download_surface(client, cfg, yr, mo, force=args.force)
                if f:
                    if isinstance(f, list):
                        downloaded.extend(f)
                    else:
                        downloaded.append(f)
            except Exception:
                logger.error(f"Surface download failed for {yr}-{mo:02d}, continuing...")

        # Small delay between requests to be nice to CDS
        time.sleep(2)

    # Write manifest
    if downloaded and not args.no_manifest:
        write_manifest(cfg, downloaded)

    logger.info(f"DONE: {len(downloaded)} files downloaded")
    
    # Summary
    total_gb = sum(f.stat().st_size for f in downloaded) / 1e9
    logger.info(f"Total: {total_gb:.1f} GB")


if __name__ == "__main__":
    main()
