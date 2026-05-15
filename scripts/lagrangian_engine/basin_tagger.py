"""HydroBASINS spatial tagging for trajectory points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import geopandas as gpd
from shapely.geometry import Point


@dataclass
class BasinTagger:
    basins: gpd.GeoDataFrame

    @classmethod
    def from_gpkg(cls, path: str | Path):
        gdf = gpd.read_file(path, layer="basins")
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        return cls(gdf)

    def tag_point(self, lat: float, lon: float) -> Optional[dict]:
        pt = Point(lon, lat)
        matches = self.basins[self.basins.geometry.contains(pt)]
        if matches.empty:
            return None
        row = matches.iloc[0]
        return {
            "HYBAS_ID": int(row.HYBAS_ID),
            "MAIN_BAS": int(row.MAIN_BAS),
            "SUB_AREA": float(row.SUB_AREA),
            "basin_name": str(row.basin_name),
        }
