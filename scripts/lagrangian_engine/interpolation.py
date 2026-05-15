"""Fast space-time interpolation for ERA5 regular lat-lon pressure grids."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator


@dataclass
class FieldInterpolator:
    """Linear interpolator for one variable at one time index.

    ERA5 latitude often descends north→south. We sort to ascending latitude so
    scipy RegularGridInterpolator behaves consistently.
    """

    values: np.ndarray
    pressure: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    has_level: bool = True

    @classmethod
    def from_dataset(cls, ds: xr.Dataset, var: str, time_index: int = 0):
        da = ds[var].isel(valid_time=time_index)
        lat = ds["latitude"].values
        lon = ds["longitude"].values

        # Ensure ascending latitude
        if lat[0] > lat[-1]:
            lat = lat[::-1]
            da = da.sel(latitude=lat)

        if "pressure_level" in da.dims:
            pressure = ds["pressure_level"].values.astype(float)
            values = da.transpose("pressure_level", "latitude", "longitude").values
            return cls(values=values, pressure=pressure, latitude=lat, longitude=lon, has_level=True)
        else:
            values = da.transpose("latitude", "longitude").values
            return cls(values=values, pressure=np.array([]), latitude=lat, longitude=lon, has_level=False)

    def scipy_interpolator(self):
        if self.has_level:
            return RegularGridInterpolator(
                (self.pressure, self.latitude, self.longitude),
                self.values,
                bounds_error=False,
                fill_value=np.nan,
            )
        return RegularGridInterpolator(
            (self.latitude, self.longitude),
            self.values,
            bounds_error=False,
            fill_value=np.nan,
        )

    def sample(self, pressure_hpa, lat, lon):
        interp = self.scipy_interpolator()
        if self.has_level:
            pts = np.column_stack([np.atleast_1d(pressure_hpa), np.atleast_1d(lat), np.atleast_1d(lon)])
        else:
            pts = np.column_stack([np.atleast_1d(lat), np.atleast_1d(lon)])
        out = interp(pts)
        return out if np.ndim(lat) else float(out[0])
