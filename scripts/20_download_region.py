#!/usr/bin/env python3
"""
Multi-region ERA5 Download Scheduler
====================================
Downloads ERA5 data for a specified region and year. Designed to be called
daily via cron to download one year per run, working backward from 2026→2014.

Usage:
  python scripts/20_download_region.py --region india --year 2026
  python scripts/20_download_region.py --region china --year 2026
  python scripts/20_download_region.py --list-regions
"""

import argparse, logging, subprocess, sys, time, zipfile
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

REGIONS = {
    "india": {
        "name": "India/South Asia",
        "bbox": {"north": 40, "west": 65, "south": 5, "east": 100},
        "storage": "/Volumes/GC_SDD1/ncdata/era5_india",
    },
    "china": {
        "name": "China/East Asia",
        "bbox": {"north": 55, "west": 70, "south": 15, "east": 140},
        "storage": "/Volumes/GC_SDD1/ncdata/era5_china",
    },
}

# CDS variables — same as South America
PRESSURE_LEVEL_VARS = {
    "u": "u_component_of_wind",
    "v": "v_component_of_wind",
    "q": "specific_humidity",
    "w": "vertical_velocity",
    "t": "temperature",
    "z": "geopotential",
}

SURFACE_INSTANT_VARS = [
    "vertical_integral_of_eastward_water_vapour_flux",
    "vertical_integral_of_northward_water_vapour_flux",
    "vertical_integral_of_divergence_of_moisture_flux",
    "total_column_water_vapour",
]

SURFACE_ACCUM_VARS = [
    "evaporation",
    "total_precipitation",
]

PRESSURE_LEVELS = [
    "1", "2", "3", "5", "7", "10", "20", "30", "50", "70",
    "100", "125", "150", "175", "200", "225", "250", "300",
    "350", "400", "450", "500", "550", "600", "650", "700",
    "750", "775", "800", "825", "850", "875", "900", "925",
    "950", "975", "1000",
]


def download_month(region: dict, year: int, month: int) -> bool:
    """Download one month of ERA5 data for a region. Returns True if complete."""
    import cdsapi

    client = cdsapi.Client()
    bbox = region["bbox"]
    area = [bbox["north"], bbox["west"], bbox["south"], bbox["east"]]
    base = Path(region["storage"])
    ym = f"{year}{month:02d}"

    # Directories
    pl_dir = base / "pressure_levels" / str(year)
    sfc_dir = base / "surface" / str(year)
    pl_dir.mkdir(parents=True, exist_ok=True)
    sfc_dir.mkdir(parents=True, exist_ok=True)

    # Check if month already complete
    existing_pl = list(pl_dir.glob(f"era5_*_pl_*_{ym}.nc"))
    existing_sfc_inst = (sfc_dir / f"era5_*_sfc_instant_{ym}.nc")
    existing_sfc_accum = (sfc_dir / f"era5_*_sfc_accum_{ym}.nc")
    if len(existing_pl) == 6:
        logger.info(f"  {ym}: all 6 PL files exist, skipping pressure levels")
    if list(sfc_dir.glob(f"era5_*_sfc_instant_{ym}.nc")) and list(sfc_dir.glob(f"era5_*_sfc_accum_{ym}.nc")):
        logger.info(f"  {ym}: surface files exist, skipping surface")
        if len(existing_pl) == 6:
            return True

    # Build day list
    import calendar
    n_days = calendar.monthrange(year, month)[1]
    days = [f"{d:02d}" for d in range(1, n_days + 1)]

    # Pressure level variables — one per request
    for var_short, var_cds in PRESSURE_LEVEL_VARS.items():
        out_file = pl_dir / f"era5_{region['name'].split('/')[0].lower().replace(' ','_')}_pl_{var_short}_{ym}.nc"
        if out_file.exists() and out_file.stat().st_size > 1_000_000:
            logger.info(f"    PL {var_short} {ym}: exists, skipping")
            continue
        logger.info(f"    PL {var_short} {ym}: requesting...")
        try:
            client.retrieve(
                "reanalysis-era5-pressure-levels",
                {
                    "product_type": "reanalysis",
                    "variable": var_cds,
                    "pressure_level": PRESSURE_LEVELS,
                    "year": str(year),
                    "month": f"{month:02d}",
                    "day": days,
                    "time": ["00:00", "06:00", "12:00", "18:00"],
                    "area": area,
                    "format": "netcdf",
                },
                str(out_file),
            )
            size_mb = out_file.stat().st_size / 1e6
            logger.info(f"    PL {var_short} {ym}: done ({size_mb:.0f} MB)")
        except Exception as e:
            logger.error(f"    PL {var_short} {ym}: FAILED — {e}")
            return False

    # Surface — single request (CDS returns ZIP for mixed step types)
    sfc_zip = sfc_dir / f"era5_{region['name'].split('/')[0].lower().replace(' ','_')}_sfc_{ym}.zip"
    sfc_instant = sfc_dir / f"era5_{region['name'].split('/')[0].lower().replace(' ','_')}_sfc_instant_{ym}.nc"
    sfc_accum = sfc_dir / f"era5_{region['name'].split('/')[0].lower().replace(' ','_')}_sfc_accum_{ym}.nc"

    if not (sfc_instant.exists() and sfc_accum.exists()):
        logger.info(f"    SFC {ym}: requesting...")
        try:
            client.retrieve(
                "reanalysis-era5-single-levels",
                {
                    "product_type": "reanalysis",
                    "variable": SURFACE_INSTANT_VARS + SURFACE_ACCUM_VARS,
                    "year": str(year),
                    "month": f"{month:02d}",
                    "day": days,
                    "time": ["00:00", "06:00", "12:00", "18:00"],
                    "area": area,
                    "format": "netcdf",
                },
                str(sfc_zip),
            )
            # Extract if ZIP
            if zipfile.is_zipfile(sfc_zip):
                logger.info(f"    SFC {ym}: extracting ZIP...")
                with zipfile.ZipFile(sfc_zip) as zf:
                    for member in zf.namelist():
                        if "instant" in member.lower():
                            zf.extract(member, sfc_dir)
                            (sfc_dir / member).rename(sfc_instant)
                        elif "accum" in member.lower():
                            zf.extract(member, sfc_dir)
                            (sfc_dir / member).rename(sfc_accum)
                sfc_zip.unlink()
            size_mb = (sfc_instant.stat().st_size + sfc_accum.stat().st_size) / 1e6
            logger.info(f"    SFC {ym}: done ({size_mb:.0f} MB)")
        except Exception as e:
            logger.error(f"    SFC {ym}: FAILED — {e}")
            return False

    return True


def main():
    ap = argparse.ArgumentParser(description="Download ERA5 for a region+year")
    ap.add_argument("--region", required=True, choices=list(REGIONS) + ["list"])
    ap.add_argument("--year", type=int)
    ap.add_argument("--months", default=None, help="Comma-separated months, default all 12")
    ap.add_argument("--list-regions", action="store_true")
    args = ap.parse_args()

    if args.list_regions or args.region == "list":
        for slug, r in REGIONS.items():
            print(f"  {slug:>8}: {r['name']} — {r['bbox']}")
        return

    region = REGIONS[args.region]
    year = args.year
    months = [int(m) for m in args.months.split(",")] if args.months else list(range(1, 13))

    logger.info(f"Region: {region['name']} | Year: {year} | Months: {len(months)}")
    logger.info(f"Storage: {region['storage']}")

    success = 0
    for month in months:
        logger.info(f"--- {year}-{month:02d} ---")
        t0 = time.time()
        ok = download_month(region, year, month)
        elapsed = time.time() - t0
        if ok:
            success += 1
            logger.info(f"  {year}-{month:02d}: OK ({elapsed:.0f}s)")
        else:
            logger.error(f"  {year}-{month:02d}: FAILED — stopping")
            break

    logger.info(f"Done: {success}/{len(months)} months successful")


if __name__ == "__main__":
    main()
