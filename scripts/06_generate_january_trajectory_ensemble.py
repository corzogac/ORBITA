#!/usr/bin/env python3
"""Generate a January 2023 trajectory ensemble for the platform.

This is an intermediate scientific/prototype run: 2D isobaric trajectories with
ERA5 time-dependent u/v winds and RK4 stepping. It gives the platform a real
multi-day/multi-release trajectory ensemble for the 30-day slider and agreement
visualization while the full 3D moisture-uptake engine is being built.

It intentionally does NOT emit `uptake_kg` or `evap_kg`, because evaporation
attribution requires the next production step (PBL/evaporation/moisture budget).
The platform will therefore keep labeling contributions as a path-contact proxy.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import Point
from tqdm import tqdm

EARTH_RADIUS_M = 6_371_000.0
BASE_ERA5 = Path("/Volumes/GC_SDD1/ncdata/era5_sa")
ROOT = Path(__file__).resolve().parents[1]

TARGETS = {
    "Bogotá": {"lat": 4.7110, "lon": -74.0721},
    "Manizales": {"lat": 5.0703, "lon": -75.5138},
}


def load_basin_targets():
    """Load all HydroBASINS L6 basin centroids as release points."""
    gpkg = ROOT / "data/hydrobasins/orinoco_l6_basins.gpkg"
    gdf = gpd.read_file(gpkg)
    targets = {}
    for _, row in gdf.iterrows():
        c = row.geometry.centroid
        hybas = str(int(row["HYBAS_ID"]))
        targets[f"HB6_{hybas}"] = {"lat": c.y, "lon": c.x}
    return targets


@dataclass
class WindSample:
    u: float
    v: float
    q: float | None = None


class TimeWindSampler:
    """Time + pressure + lat/lon interpolation over one ERA5 month."""

    def __init__(self, ds: xr.Dataset):
        if ds.latitude.values[0] > ds.latitude.values[-1]:
            ds = ds.sortby("latitude")
        self.ds = ds
        self.times = pd.to_datetime(ds.valid_time.values)
        self.time_seconds = self.times.astype("int64") / 1e9
        self.pressure = ds.pressure_level.values.astype(float)
        self.lat = ds.latitude.values.astype(float)
        self.lon = ds.longitude.values.astype(float)
        self._cache: dict[tuple[str, int], RegularGridInterpolator] = {}

    def _interp3(self, var: str, time_index: int) -> RegularGridInterpolator:
        key = (var, time_index)
        if key not in self._cache:
            arr = self.ds[var].isel(valid_time=time_index).transpose("pressure_level", "latitude", "longitude").values
            self._cache[key] = RegularGridInterpolator(
                (self.pressure, self.lat, self.lon),
                arr,
                bounds_error=False,
                fill_value=np.nan,
            )
        return self._cache[key]

    def sample_var(self, var: str, when: pd.Timestamp, pressure_hpa: float, lat: float, lon: float) -> float:
        ts = when.value / 1e9
        if ts < self.time_seconds[0] or ts > self.time_seconds[-1]:
            return float("nan")
        hi = int(np.searchsorted(self.time_seconds, ts, side="left"))
        if hi == 0:
            lo = hi = 0
            w = 0.0
        elif hi >= len(self.time_seconds):
            lo = hi = len(self.time_seconds) - 1
            w = 0.0
        elif self.time_seconds[hi] == ts:
            lo = hi
            w = 0.0
        else:
            lo = hi - 1
            w = (ts - self.time_seconds[lo]) / (self.time_seconds[hi] - self.time_seconds[lo])
        pt = np.array([[pressure_hpa, lat, lon]], dtype=float)
        v0 = float(self._interp3(var, lo)(pt)[0])
        if lo == hi:
            return v0
        v1 = float(self._interp3(var, hi)(pt)[0])
        return (1 - w) * v0 + w * v1

    def wind(self, when: pd.Timestamp, pressure_hpa: float, lat: float, lon: float) -> WindSample:
        return WindSample(
            u=self.sample_var("u", when, pressure_hpa, lat, lon),
            v=self.sample_var("v", when, pressure_hpa, lat, lon),
            q=self.sample_var("q", when, pressure_hpa, lat, lon) if "q" in self.ds else None,
        )


def tendency(lat: float, lon: float, u: float, v: float) -> tuple[float, float]:
    """Forward-time derivative in degrees per second."""
    lat_rad = math.radians(lat)
    cos_lat = max(math.cos(lat_rad), 1e-6)
    dlat_dt = math.degrees(v / EARTH_RADIUS_M)
    dlon_dt = math.degrees(u / (EARTH_RADIUS_M * cos_lat))
    return dlat_dt, dlon_dt


def rk4_backward_step(
    sampler: TimeWindSampler,
    when: pd.Timestamp,
    lat: float,
    lon: float,
    pressure_hpa: float,
    dt_seconds: float = -3600.0,
) -> tuple[float, float, WindSample]:
    """One backward RK4 step in 2D at a fixed pressure level."""
    s1 = sampler.wind(when, pressure_hpa, lat, lon)
    if not np.isfinite(s1.u) or not np.isfinite(s1.v):
        return float("nan"), float("nan"), s1
    k1_lat, k1_lon = tendency(lat, lon, s1.u, s1.v)

    t2 = when + pd.to_timedelta(dt_seconds / 2, unit="s")
    s2 = sampler.wind(t2, pressure_hpa, lat + k1_lat * dt_seconds / 2, lon + k1_lon * dt_seconds / 2)
    k2_lat, k2_lon = tendency(lat + k1_lat * dt_seconds / 2, lon + k1_lon * dt_seconds / 2, s2.u, s2.v)

    s3 = sampler.wind(t2, pressure_hpa, lat + k2_lat * dt_seconds / 2, lon + k2_lon * dt_seconds / 2)
    k3_lat, k3_lon = tendency(lat + k2_lat * dt_seconds / 2, lon + k2_lon * dt_seconds / 2, s3.u, s3.v)

    t4 = when + pd.to_timedelta(dt_seconds, unit="s")
    s4 = sampler.wind(t4, pressure_hpa, lat + k3_lat * dt_seconds, lon + k3_lon * dt_seconds)
    k4_lat, k4_lon = tendency(lat + k3_lat * dt_seconds, lon + k3_lon * dt_seconds, s4.u, s4.v)

    new_lat = lat + dt_seconds * (k1_lat + 2 * k2_lat + 2 * k3_lat + k4_lat) / 6
    new_lon = lon + dt_seconds * (k1_lon + 2 * k2_lon + 2 * k3_lon + k4_lon) / 6
    return new_lat, new_lon, s1


def open_pressure_month(year: int, month: int) -> xr.Dataset:
    parts = []
    for var in ["u", "v", "q"]:
        p = BASE_ERA5 / "pressure_levels" / str(year) / f"era5_sa_pl_{var}_{year}{month:02d}.nc"
        if not p.exists():
            raise FileNotFoundError(p)
        parts.append(xr.open_dataset(p, engine="netcdf4")[[var]])
    return xr.merge(parts, compat="override")


def tag_basins(points: pd.DataFrame) -> pd.DataFrame:
    basin_path = ROOT / "data" / "hydrobasins" / "orinoco_l6_basins.gpkg"
    basins = gpd.read_file(basin_path)
    if basins.crs is None:
        basins = basins.set_crs("EPSG:4326")
    geom = [Point(xy) for xy in zip(points["lon"], points["lat"])]
    gdf = gpd.GeoDataFrame(points, geometry=geom, crs="EPSG:4326")
    keep = [c for c in ["HYBAS_ID", "MAIN_BAS", "SUB_AREA", "NEXT_DOWN", "DIST_MAIN", "basin_name", "geometry"] if c in basins.columns]
    tagged = gpd.sjoin(gdf, basins[keep], how="left", predicate="within")
    tagged = pd.DataFrame(tagged.drop(columns=[c for c in ["geometry", "index_right"] if c in tagged.columns]))
    tagged["HYBAS_ID"] = tagged["HYBAS_ID"].astype("Int64")
    tagged["MAIN_BAS"] = tagged["MAIN_BAS"].astype("Int64")
    tagged["basin_name"] = tagged["HYBAS_ID"].apply(lambda x: f"HB_{int(x)}" if pd.notna(x) else "ocean_or_outside_hydrobasins")
    return tagged


def generate(
    start: str,
    end: str,
    levels: Iterable[int],
    hours_back: int,
    release_freq: str,
    step_hours: int,
    year: int = 2023,
    month: int = 1,
    targets: dict | None = None,
) -> pd.DataFrame:
    ds = open_pressure_month(year, month)
    sampler = TimeWindSampler(ds)
    releases = pd.date_range(start, end, freq=release_freq)
    rows = []
    levels = list(levels)
    hour_marks = list(range(0, hours_back + 1, step_hours))
    if hour_marks[-1] != hours_back:
        hour_marks.append(hours_back)
    if targets is None:
        targets = TARGETS
    for release_time in tqdm(releases, desc="release times"):
        for target, loc in targets.items():
            for level in levels:
                lat, lon = loc["lat"], loc["lon"]
                tid = f"{target}_{release_time:%Y%m%dT%H}_{level}hpa"
                for i, h in enumerate(hour_marks):
                    when = release_time - pd.to_timedelta(h, unit="h")
                    s = sampler.wind(when, level, lat, lon)
                    rows.append(
                        {
                            "trajectory_id": tid,
                            "target": target,
                            "release_time_utc": release_time.isoformat() + "Z",
                            "release_date": release_time.date().isoformat(),
                            "release_hour_utc": int(release_time.hour),
                            "hour_back": h,
                            "valid_time_utc": when.isoformat() + "Z",
                            "lat": lat,
                            "lon": lon,
                            "pressure_hpa": level,
                            "u_ms": s.u,
                            "v_ms": s.v,
                            "q_kgkg": s.q,
                            "source_mode": f"2d_isobaric_rk4_time_dependent_prototype_{step_hours}h_step",
                        }
                    )
                    if i < len(hour_marks) - 1:
                        dt = -float(hour_marks[i + 1] - h) * 3600.0
                        lat, lon, _ = rk4_backward_step(sampler, when, lat, lon, level, dt_seconds=dt)
                        if not np.isfinite(lat) or not np.isfinite(lon):
                            break
    df = pd.DataFrame(rows)
    return tag_basins(df)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--month", type=int, default=1)
    ap.add_argument("--start", default=None, help="Default: first day of --year/--month 00:00")
    ap.add_argument("--end", default=None, help="Default: last day of --year/--month 18:00")
    ap.add_argument("--hours-back", type=int, default=72)
    ap.add_argument("--step-hours", type=int, default=6, help="RK4 output/integration step in hours for the prototype ensemble")
    ap.add_argument("--release-freq", default="6h")
    ap.add_argument("--levels", default="850,700,500")
    ap.add_argument("--out-prefix", default=None, help="Output basename without extension")
    ap.add_argument("--release-from", default="targets", choices=["targets", "basins"],
                    help="targets = Bogotá+Manizales (default); basins = all L6 centroids")
    args = ap.parse_args()

    if args.start is None:
        args.start = f"{args.year}-{args.month:02d}-01 00:00"
    if args.end is None:
        month_start = pd.Timestamp(args.year, args.month, 1)
        next_month = month_start + pd.offsets.MonthBegin(1)
        args.end = f"{(next_month - pd.Timedelta(days=1)):%Y-%m-%d} 18:00"

    if args.release_from == "basins":
        targets = load_basin_targets()
        if args.release_freq == "6h":
            args.release_freq = "1d"  # throttle for all-basin mode
        print(f"Release-from basins: {len(targets)} points, freq={args.release_freq}")
    else:
        targets = None

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    out_dir = ROOT / "results" / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = args.out_prefix or f"trajectory_ensemble_{args.year}{args.month:02d}_2d_rk4"
    out_csv = out_dir / f"{out_prefix}.csv"
    out_parquet = out_dir / f"{out_prefix}.parquet"

    df = generate(args.start, args.end, levels, args.hours_back, args.release_freq, args.step_hours, args.year, args.month, targets)
    df.to_csv(out_csv, index=False)
    df.to_parquet(out_parquet, index=False)
    summary = {
        "year": args.year,
        "month": args.month,
        "start": args.start,
        "end": args.end,
        "rows": int(len(df)),
        "trajectories": int(df["trajectory_id"].nunique()),
        "targets": sorted(df["target"].unique().tolist()),
        "release_dates": [str(df["release_date"].min()), str(df["release_date"].max())],
        "levels_hpa": levels,
        "hours_back": args.hours_back,
        "step_hours": args.step_hours,
        "method": "2D fixed-pressure RK4 with time-dependent ERA5 u/v/q; no evaporation uptake yet",
        "csv": str(out_csv.relative_to(ROOT)),
        "parquet": str(out_parquet.relative_to(ROOT)),
    }
    (out_dir / f"{out_prefix}_summary.json").write_text(
        pd.Series(summary).to_json(indent=2), encoding="utf-8"
    )
    print(summary)


if __name__ == "__main__":
    main()
