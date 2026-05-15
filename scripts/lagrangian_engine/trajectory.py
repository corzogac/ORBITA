"""Prototype Lagrangian back-trajectory integration.

This first implementation is intentionally conservative: it supports 2D
isobaric backward trajectories on a fixed pressure level. The 3D version will
extend this with vertical velocity (omega) and pressure-coordinate integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import numpy as np

EARTH_RADIUS_M = 6_371_000.0


@dataclass
class TrajectoryPoint:
    hour_back: float
    lat: float
    lon: float
    pressure_hpa: float
    u_ms: float
    v_ms: float


@dataclass
class Trajectory:
    target_name: str
    release_lat: float
    release_lon: float
    pressure_hpa: float
    points: List[TrajectoryPoint]


def advect_backward_2d(lat, lon, u_ms, v_ms, dt_seconds):
    """Move one backward step on a sphere using local u/v wind.

    For backward trajectory, position(t-dt) = position(t) - wind * dt.
    u positive eastward, v positive northward.
    """
    lat_rad = np.deg2rad(lat)
    dlat = -(v_ms * dt_seconds) / EARTH_RADIUS_M
    dlon = -(u_ms * dt_seconds) / (EARTH_RADIUS_M * np.cos(lat_rad))
    return lat + np.rad2deg(dlat), lon + np.rad2deg(dlon)


def integrate_isobaric_backward(
    target_name: str,
    lat0: float,
    lon0: float,
    pressure_hpa: float,
    wind_sampler: Callable[[float, float, float, int], tuple[float, float]],
    n_steps: int = 24,
    dt_hours: float = 1.0,
) -> Trajectory:
    """Integrate a simple fixed-pressure back-trajectory.

    wind_sampler(pressure_hpa, lat, lon, step_index) returns (u, v) in m/s.
    step_index can be used by the caller to choose time slices.
    """
    lat, lon = float(lat0), float(lon0)
    points: List[TrajectoryPoint] = []
    dt_seconds = dt_hours * 3600.0

    for step in range(n_steps + 1):
        u, v = wind_sampler(pressure_hpa, lat, lon, step)
        points.append(TrajectoryPoint(step * dt_hours, lat, lon, pressure_hpa, u, v))
        if not np.isfinite(u) or not np.isfinite(v):
            break
        lat, lon = advect_backward_2d(lat, lon, u, v, dt_seconds)

    return Trajectory(target_name, lat0, lon0, pressure_hpa, points)
