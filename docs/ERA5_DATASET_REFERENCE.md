# ORBITA — ERA5 Dataset Reference

## Active Download (South America, 2023 done)

### CDS Dataset: `reanalysis-era5-pressure-levels`
**URL:** https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels

| CDS Variable | ERA5 Name | Units | File | Used For |
|---|---|---|---|---|
| `u_component_of_wind` | u | m/s | `era5_sa_pl_u_YYYYMM.nc` | Trajectory wind |
| `v_component_of_wind` | v | m/s | `era5_sa_pl_v_YYYYMM.nc` | Trajectory wind |
| `specific_humidity` | q | kg/kg | `era5_sa_pl_q_YYYYMM.nc` | Moisture tracking |
| `vertical_velocity` | w | Pa/s | `era5_sa_pl_w_YYYYMM.nc` | 3D trajectories |
| `temperature` | t | K | `era5_sa_pl_t_YYYYMM.nc` | Thermodynamics |
| `geopotential` | z | m²/s² | `era5_sa_pl_z_YYYYMM.nc` | Pressure levels |

**Resolution:** 0.25° × 0.25°, 37 levels (1000→1 hPa), 6-hourly
**Per month:** ~600 MB × 6 = ~3.6 GB
**Region:** South America (15°N→60°S, 85°W→30°W)

### CDS Dataset: `reanalysis-era5-single-levels`
**URL:** https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels

| CDS Variable | ERA5 Name | Units | File | Used For |
|---|---|---|---|---|
| `vertical_integral_of_eastward_water_vapour_flux` | viwve | kg/m/s | `era5_sa_sfc_instant_YYYYMM.nc` | IVT-E |
| `vertical_integral_of_northward_water_vapour_flux` | viwvn | kg/m/s | `era5_sa_sfc_instant_YYYYMM.nc` | IVT-N |
| `vertical_integral_of_divergence_of_moisture_flux` | vimd | kg/m²/s | `era5_sa_sfc_instant_YYYYMM.nc` | ∇·IVT |
| `total_column_water_vapour` | tcwv | kg/m² | `era5_sa_sfc_instant_YYYYMM.nc` | Column moisture |
| `evaporation` | e | m | `era5_sa_sfc_accum_YYYYMM.nc` | Evap (accumulated) |
| `total_precipitation` | tp | m | `era5_sa_sfc_accum_YYYYMM.nc` | Precip (accumulated) |

**Resolution:** 0.25° × 0.25°, 6-hourly
**Per month:** instant ~200 MB + accum ~25 MB = ~225 MB
**Region:** South America (same as pressure levels)

## Expansion Regions

### India
- BBox: 5°N→40°N, 65°E→100°E
- Same variables, same CDS datasets
- Per month: ~same sizes

### China
- BBox: 15°N→55°N, 70°E→140°E
- Same variables, same CDS datasets
- Per month: ~same sizes

## Download Strategy

### CDS API limits:
- 1 pressure-level variable per request (CDS merges multi-variable PL requests)
- 1 surface request (ZIP with instant+accum)
- Sequential only (concurrent requests fail with "Request is queued")
- Queue times: 1–30 minutes per request during busy periods

### Per-month total: 7 requests (6 PL variables + 1 surface)
### Per-year total: 84 requests
### Time per year: ~2–4 hours (depending on CDS queue)

## Existing Data Inventory

| Location | Coverage | Size |
|---|---|---|
| `GC_SDD1/ncdata/era5_sa/` | South America 2023 (12 months) | 46 GB |
| `Extreme SSD/Work/ERA5/downloads/` | Yearly IVT/EPQ 2023-2026 | ~50 MB |
| `Extreme SSD/Work/ERA5/` | Monthly climatology 1959-2026 | ~3.5 GB |
| `Extreme SSD/Work/ERA5/data/lagrangian/` | Lagrangian 4D 2023-2026 | 47 GB |
| `Extreme SSD/Work/Amazon/SIG/` | Amazon basin shapefiles | ZIP |

## Pre-Existing Analysis (Extreme SSD/Work/ERA5/archive/2026-03-21/)

Generated figures from previous Amazon/Orinoquia analysis:
- IVT climatology + seasonal maps
- Lagrangian trajectory plots
- Basin rank heatmaps + timeseries
- Eulerian neighbor flux diagrams
- Anomaly maps (z-score, Spearman correlation, rank shift)
- Model performance dashboard
- Wind field animations (u10/v10)

## CDS Download Command Reference

```python
# Pressure level — one variable at a time
c.retrieve('reanalysis-era5-pressure-levels', {
    'product_type': 'reanalysis',
    'variable': 'u_component_of_wind',
    'pressure_level': ['1','2','3','5','7','10','20','30','50','70',
                       '100','125','150','175','200','225','250','300',
                       '350','400','450','500','550','600','650','700',
                       '750','775','800','825','850','875','900','925',
                       '950','975','1000'],
    'year': '2023', 'month': '01',
    'day': ['01','02',...,'31'],
    'time': ['00:00','06:00','12:00','18:00'],
    'area': [15, -85, -60, -30],  # N, W, S, E
    'format': 'netcdf'
}, 'era5_sa_pl_u_202301.nc')

# Surface — single request returns ZIP
c.retrieve('reanalysis-era5-single-levels', {
    'product_type': 'reanalysis',
    'variable': ['vertical_integral_of_eastward_water_vapour_flux',
                 'vertical_integral_of_northward_water_vapour_flux',
                 'vertical_integral_of_divergence_of_moisture_flux',
                 'total_column_water_vapour',
                 'evaporation',
                 'total_precipitation'],
    'year': '2023', 'month': '01',
    'day': ['01','02',...,'31'],
    'time': ['00:00','06:00','12:00','18:00'],
    'area': [15, -85, -60, -30],
    'format': 'netcdf'
}, 'era5_sa_sfc_202301.zip')
```
