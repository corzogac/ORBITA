"""ERA5 data access helpers for Lagrangian trajectory engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

import numpy as np
import xarray as xr


@dataclass
class ERA5Month:
    """Container for one month of ERA5 fields."""

    base_path: Path
    year: int
    month: int

    def pressure_file(self, var: str) -> Path:
        return self.base_path / "pressure_levels" / str(self.year) / f"era5_sa_pl_{var}_{self.year}{self.month:02d}.nc"

    def surface_instant_file(self) -> Path:
        return self.base_path / "surface" / str(self.year) / f"era5_sa_sfc_instant_{self.year}{self.month:02d}.nc"

    def surface_accum_file(self) -> Path:
        return self.base_path / "surface" / str(self.year) / f"era5_sa_sfc_accum_{self.year}{self.month:02d}.nc"

    def open_pressure(self, vars: Iterable[str] = ("u", "v", "q", "w", "t", "z")) -> xr.Dataset:
        """Open pressure-level fields and merge by coordinates."""
        datasets = []
        for var in vars:
            p = self.pressure_file(var)
            if not p.exists():
                raise FileNotFoundError(f"Missing pressure-level file: {p}")
            datasets.append(xr.open_dataset(p, engine="netcdf4"))
        return xr.merge(datasets, compat="override")

    def open_surface(self) -> xr.Dataset:
        """Open surface instant + accumulated fields and merge."""
        inst = self.surface_instant_file()
        acc = self.surface_accum_file()
        if not inst.exists():
            raise FileNotFoundError(f"Missing surface instant file: {inst}")
        if not acc.exists():
            raise FileNotFoundError(f"Missing surface accumulated file: {acc}")
        return xr.merge([
            xr.open_dataset(inst, engine="netcdf4"),
            xr.open_dataset(acc, engine="netcdf4"),
        ], compat="override")


def normalize_longitudes(lon: np.ndarray) -> np.ndarray:
    """Normalize longitudes to [-180, 180]."""
    return ((lon + 180) % 360) - 180
