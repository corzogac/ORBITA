#!/usr/bin/env python3
"""Publish ORBITA prototype trajectories to an efficient partitioned Parquet layout.

The local platform currently keeps monthly prototype Parquet files in
results/tables. This script writes a cloud-optimized Hive-style partitioned
layout by year/month so downstream jobs can read only the months they need.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "results" / "tables"
BUCKET_PREFIX = "gs://rs-weather-data-orbit/trajectories/prototype_2d_rk4/partitioned"


def sh(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def monthly_files(year: int) -> list[Path]:
    return sorted(TABLES.glob(f"trajectory_ensemble_{year}[0-9][0-9]_2d_rk4.parquet"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--bucket-prefix", default=BUCKET_PREFIX)
    ap.add_argument("--keep-local", action="store_true")
    args = ap.parse_args()

    files = monthly_files(args.year)
    if not files:
        raise FileNotFoundError(f"No monthly Parquet files for {args.year} in {TABLES}")

    tmp_root = Path(tempfile.mkdtemp(prefix="orbita_partitioned_"))
    try:
        rows = 0
        months = []
        for path in files:
            df = pd.read_parquet(path)
            if df.empty:
                continue
            dt = pd.to_datetime(df["release_date"])
            df["year"] = dt.dt.year.astype("int16")
            df["month"] = dt.dt.month.astype("int8")
            month = int(df["month"].iloc[0])
            months.append(f"{args.year}-{month:02d}")
            out_dir = tmp_root / f"year={args.year}" / f"month={month:02d}"
            out_dir.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, out_dir / "part-000.parquet", compression="zstd")
            rows += len(df)

        sh(["gsutil", "-m", "rsync", "-r", str(tmp_root), args.bucket_prefix])
        print({"rows": rows, "months": months, "bucket_prefix": args.bucket_prefix})
        if args.keep_local:
            local = ROOT / "results" / "cloud_export" / "prototype_2d_rk4_partitioned"
            if local.exists():
                shutil.rmtree(local)
            shutil.copytree(tmp_root, local)
            print(f"Kept local copy: {local}")
    finally:
        if not args.keep_local:
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
