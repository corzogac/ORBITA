# Atmospheric Rivers Orinoquia — Project Design

## Water Vapor Transport from Orinoquia to the Colombian Andes

**Version:** 1.0 — 2026-05-15
**Author:** Gerald Corzo
**Status:** Design + implementation prototype — ERA5 download, trajectory engine, and interactive platform in progress

---

## 1. Scientific Objective

Quantify the contribution of evaporation from individual Orinoquia sub-basins (HydroBASINS level 5) to the atmospheric water vapor that reaches Bogotá and Manizales, using Lagrangian back-trajectory analysis driven by ERA5 reanalysis. Provide monthly-resolution diagnostics including source region, transport pathway, time-of-displacement, and 12-month climatological graphs.

### Core Questions

1. **Where does the water vapor come from?** — Back-trajectories from target cities identify source regions
2. **How much does each sub-basin contribute?** — Moisture uptake tagged by basin along trajectories
3. **How long does it take?** — Time-of-displacement from evaporation source to target
4. **How does this vary seasonally?** — Monthly and 12-month climatologies
5. **What are the "flying rivers"?** — Coherent atmospheric moisture transport pathways visualized in 3D

---

## 2. Methodology: Lagrangian Particle Dispersion with Moisture Accounting

### 2.1 Rationale

We evaluated four approaches and selected **custom Lagrangian particle tracking**:

| Method | Type | Trajectories | Evap contribution | Time-of-displacement | ERA5-native |
|--------|------|:---:|:---:|:---:|:---:|
| **Lagrangian particles (chosen)** | Lagrangian | ✓ | ✓ | ✓ | ✓ |
| WAM-2layers | Eulerian | ✗ | ✓ | ✗ | ✓ |
| HYSPLIT | Lagrangian | ✓ | ✗* | ✓ | via ARL |
| LAGRANTO | Lagrangian | ✓ | ✗* | ✓ | ✓ |

*Can be added with custom post-processing, but not native.

The Lagrangian approach directly answers "where does this air parcel come from and what did it pick up along the way?" — the exact question Gerald poses.

### 2.2 Particle Back-Trajectory Algorithm

**Release strategy:** From each target location (Bogotá: 4.71°N, 74.07°W; Manizales: 5.07°N, 75.52°W), release particles at 6-hourly intervals, distributed across 3–5 vertical levels within the lower/mid troposphere (boundary layer, 850 hPa, 700 hPa, 500 hPa, 300 hPa). This captures the full column of moisture transport.

**Backward integration:**
- Use 4th-order Runge-Kutta scheme
- Time step: 1 hour (sub-stepping ERA5's 6-hourly resolution)
- Wind fields: u, v on all ERA5 pressure levels, linearly interpolated in space and time
- Vertical motion: diagnosed from continuity (ω from pressure tendency) or directly from ERA5 vertical velocity
- Run backwards for 10 days (240 hours) — covers typical Amazon-to-Andes transport timescales
- Particles that leave the domain (60°S–15°N, 85°W–30°W) are terminated

**Moisture accounting along trajectories:**
For each particle at each time step:
1. Check if particle is within the planetary boundary layer (PBL height from ERA5)
2. If in PBL:
   - Record surface evaporation flux (E from ERA5, kg m⁻² s⁻¹)
   - Tag the moisture uptake with the HydroBASINS level-5 basin ID at that location
   - Record the time-of-uptake (for time-of-displacement calculation)
3. Track specific humidity changes to compute net moisture flux

**Moisture budget per particle:**
```
M_target = Σ (E_i × Δt × A_footprint) × f_transport
```
where:
- E_i = evaporation at time step i
- Δt = time step (1 hour)
- A_footprint = representative area of the particle footprint
- f_transport = fraction of moisture that survives transport (decay factor)

### 2.3 Alternative: Simplified 2D Isobaric Tracking

For initial rapid results, we can also implement a simpler 2D version:
- Track particles on a single pressure level (e.g., 850 hPa for low-level jet / flying rivers)
- This captures the main low-level moisture flux from the Orinoquia/Amazon
- Faster computation, suitable for initial exploration
- Full 3D version deployed once the pipeline is validated

---

## 3. ERA5 Data Requirements

### 3.1 Domain

South America domain covering the Amazon, Orinoquia, Andes, and Caribbean moisture sources:

```
North: 15°N
South: 60°S
West: 85°W
East: 30°W
```

Grid: 0.25° × 0.25° (ERA5 native) → ~221 × 301 = 66,521 grid points

### 3.2 Variables

**Pressure-level variables** (essential — the large dataset):
| Variable | ERA5 name | Levels | Purpose |
|----------|-----------|--------|---------|
| U wind | `u` | All 37 | Horizontal trajectory integration |
| V wind | `v` | All 37 | Horizontal trajectory integration |
| Specific humidity | `q` | All 37 | Moisture content tracking |
| Temperature | `t` | All 37 | Thermodynamic state, density/height checks |
| Geopotential | `z` | All 37 | Convert pressure levels to approximate altitude |
| Vertical velocity | `w` | All 37 | Vertical displacement (optional, ~ω can substitute) |

**Surface/single-level variables** (compact):
| Variable | ERA5 name | Purpose |
|----------|-----------|---------|
| Surface pressure | `sp` | Pressure-level → height conversion |
| Evaporation | `e` | Moisture source quantification |
| Total column water | `tcwv` | Validation, visualization |
| Vertically integrated eastward water-vapour flux | `viwve` | Direct IVT/flying-river visualization |
| Vertically integrated northward water-vapour flux | `viwvn` | Direct IVT/flying-river visualization |
| Vertically integrated divergence of moisture flux | `vimd` | Moisture convergence/divergence diagnostic |
| Boundary layer height | `blh` | Determine if particle is in PBL |
| Total precipitation | `tp` | Sink / rainfall validation at targets and along path |
| 10m U/V wind | `u10`, `v10` | Surface wind validation |
| 2m temperature | `t2m` | Surface temperature / evaporation context |
| 2m dewpoint temp | `d2m` | Surface moisture validation |
| Volumetric soil water layers 1–4 | `swvl1..4` | Soil moisture memory controlling evaporation |
| Soil temperature levels 1–4 | `stl1..4` | Land-surface thermal state |

### 3.3 Temporal Coverage

- **Period:** 1980–2024 (full ERA5 back-extension + recent years)
- **Resolution:** 6-hourly (00, 06, 12, 18 UTC)
- **Annual size estimate per variable (pressure levels):**
  - 221 × 301 grid × 37 levels × 1460 time steps × 4 bytes ≈ **14 GB/year/variable**
  - Total pressure-level data (~4 variables): **~56 GB/year**
  - Total surface data (~7 variables): **~2 GB/year**
  - **Grand total:** ~58 GB/year × 45 years ≈ **2.6 TB**

### 3.4 Storage Strategy

**Location:** `/Volumes/GC_SDD1/ncdata/era5_sa/` (external SSD, 3.1 TB available)

**Organization:**
```
era5_sa/
├── pressure_levels/
│   ├── 1980/
│   │   ├── era5_sa_pl_198001.nc    # Jan 1980, all vars, all levels, all times
│   │   ├── era5_sa_pl_198002.nc
│   │   └── ...
│   └── ...
├── surface/
│   ├── 1980/
│   │   ├── era5_sa_sfc_198001.nc
│   │   └── ...
│   └── ...
└── manifest.json                    # Download log with checksums
```

**Tiered download priority:**
1. **Tier 1** (immediate): One test year (e.g., 2023) — validate pipeline
2. **Tier 2** (working set): 2010–2024 (15 years) — main analysis period
3. **Tier 3** (climatology): 1980–2009 (30 years) — long-term background

**Download approach:** Use CDS API with monthly chunking to avoid timeouts. Each monthly file is self-contained and restartable.

---

## 4. HydroBASINS Integration

### 4.1 Basin Framework

HydroBASINS level 5 provides sub-basin delineation for the Orinoquia region:
- **Download:** HydroSHEDS HydroBASINS level 5 for South America
- **Orinoquia basins:** Extract all level-5 basins whose main stem flows into the Orinoco
- **Target count:** Approximately 200–400 level-5 basins in the Orinoquia

### 4.2 Basin Attribution

For each trajectory time step in the PBL:
1. Spatially join particle (lat, lon) to HydroBASINS level-5 polygon
2. If inside a basin polygon, attribute moisture uptake to that basin
3. For particles over the ocean (Atlantic, Caribbean, Pacific), tag as "oceanic source"
4. For particles outside any basin (non-Orinoquia land), tag as "other terrestrial"

### 4.3 Output: Basin × Month Evaporation Contribution Matrix

```
basin_id | HYBAS_ID | basin_name | month | evap_contribution_kg | pct_of_total | mean_time_displacement_h | n_particles
```

---

## 5. Visualization & Deliverables

### 5.1 Flying Rivers Map (3D atmospheric rivers)

An interactive or static visualization showing:
- Dominant moisture transport pathways (ensemble of trajectories colored by altitude)
- Source regions highlighted by evaporation contribution
- Target cities marked
- Topography backdrop (Andes)
- Monthly animation showing seasonal shifts

**Tools:** Plotly 3D / deck.gl for interactive; matplotlib + cartopy for publication figures

### 5.2 Per-Basin Monthly Contribution Graph (PRIMARY DELIVERABLE)

For any selected level-5 basin:
- 12-month bar/line chart showing monthly evaporation contribution to Bogotá and Manizales
- Stacked by target (Bogotá vs. Manizales) or separate panels
- Includes: mean time-of-displacement (secondary axis or annotation)
- Source-to-sink stream indicator showing where the moisture from this basin predominantly goes

### 5.3 Source-Region Sankey / Stream Plot

Showing the flow of water vapor:
- Source basins → Transport pathway → Target cities
- Width of streams proportional to moisture contribution
- Colored by source region type (Orinoquia basin, Amazon, Atlantic, etc.)

### 5.4 Seasonal Climatology Maps

Gridded maps showing:
- Mean evaporation contribution to target cities (kg m⁻² month⁻¹)
- Dominant transport pathways (wind roses at key locations)
- Seasonal shifts in source regions

### 5.5 Basin Selection Dashboard

An interactive tool (Streamlit or static HTML) to:
- Select any level-5 basin by clicking on a map or from dropdown
- Display its monthly contribution graph
- Show source-to-sink stream visualization
- Export data as CSV

---

## 6. Project Structure

```
atmospheric_rivers_orinoquia/
├── docs/
│   ├── DESIGN.md                    # This document
│   ├── METHODOLOGY.md               # Detailed algorithm docs
│   └── REFERENCES.md                # Literature review
├── scripts/
│   ├── 01_download_era5.py          # CDS API downloader
│   ├── 02_verify_downloads.py       # Checksum + completeness
│   ├── 03_prepare_hydrobasins.py    # Fetch + clip HydroBASINS L5
│   ├── 04_run_lagrangian.py         # Core particle tracking engine
│   ├── 05_aggregate_basin.py        # Basin-level moisture accounting
│   ├── 06_monthly_contributions.py  # Per-basin 12-month analysis
│   ├── 07_flying_rivers_viz.py      # 3D trajectory visualization
│   ├── 08_basin_dashboard.py        # Interactive selection dashboard
│   └── lagrangian_engine/
│       ├── __init__.py
│       ├── trajectory.py            # RK4 integrator
│       ├── interpolation.py         # Space-time interpolation
│       ├── moisture.py              # Moisture accounting
│       └── basin_tagger.py          # HydroBASINS spatial join
├── notebooks/
│   ├── 01_era5_exploration.ipynb
│   ├── 02_trajectory_validation.ipynb
│   └── 03_basin_analysis.ipynb
├── config/
│   ├── targets.yaml                 # Target cities + release params
│   ├── era5_variables.yaml          # Variable specs + CDS params
│   └── hydrobasins.yaml             # Basin level, region, filters
├── data/
│   └── hydrobasins/                 # Local HydroBASINS cache
│       └── hybas_sa_lev05_v1c/
├── results/
│   ├── figures/
│   │   ├── flying_rivers/
│   │   ├── basin_contributions/
│   │   └── climatology/
│   └── tables/
│       ├── basin_monthly_contributions.csv
│       └── basin_annual_summary.csv
├── requirements.txt
└── README.md
```

---

## 7. Implementation Phases

### Phase 0: Environment Setup (1 session)
- Create conda/venv environment with: `xarray`, `dask`, `cdsapi`, `metpy`, `cartopy`, `geopandas`, `rasterio`, `scipy`, `plotly`
- Install HydroBASINS level 5 for South America
- Set up external SSD paths and verify disk space
- Configure CDS API (already done)

### Phase 1: ERA5 Data Download (automated, multi-day)
- Download 1 test month (validate pipeline)
- Download 2023 full year (pressure levels + surface)
- Download 2010–2024 working set (~870 GB)
- Run verification script (checksums, completeness)
- **Storage:** `/Volumes/GC_SDD1/ncdata/era5_sa/`

### Phase 2: Lagrangian Engine (2–3 sessions)
- Implement RK4 trajectory integrator
- Implement space-time interpolation (xarray + scipy)
- Implement moisture accounting along trajectories
- Validate against known transport patterns (Amazon → Andes)
- Test with 1 month of data

### Phase 3: Full Back-Trajectory Run (1 session + computation)
- Run back-trajectories from Bogotá and Manizales for 2010–2024
- Release 5 vertical levels × 4 times/day = 20 trajectories/day/target
- Total: 20 × 365 × 15 × 2 targets ≈ 219,000 trajectories
- Computation time estimate: ~2–4 hours on M-series Mac
- Parallelize with dask or multiprocessing

### Phase 4: Basin Attribution & Analysis (2–3 sessions)
- Spatial join of trajectory points to HydroBASINS level 5
- Compute evaporation contribution per basin per month
- Compute time-of-displacement statistics
- Generate basin × month contribution matrix
- Statistical analysis (trends, seasonality, anomalies)

### Phase 5: Visualization & Dashboard (2–3 sessions)
- Flying rivers 3D visualization
- Per-basin 12-month contribution graphs
- Source-to-sink stream diagrams
- Interactive basin selection dashboard (Streamlit)
- Seasonal climatology maps

### Phase 6: Documentation & Publication (1–2 sessions)
- Methodology write-up
- Figure polishing for publication
- Integration with existing Orinoquia platform

---

## 8. Technical Notes

### 8.1 Lagrangian Integration Details

The core trajectory equation:
```
dx/dt = u(x, y, p, t)
dy/dt = v(x, y, p, t)
dp/dt = ω(x, y, p, t)   # vertical motion in pressure coordinates
```

4th-order Runge-Kutta for position (x, y, p) at time t - Δt:
```
k1 = Δt × v(x_t, t)
k2 = Δt × v(x_t + k1/2, t + Δt/2)  # backward: t + Δt/2 means earlier time
k3 = Δt × v(x_t + k2/2, t + Δt/2)
k4 = Δt × v(x_t + k3, t + Δt)
x_{t-Δt} = x_t - (k1 + 2k2 + 2k3 + k4)/6  # backward integration
```

### 8.2 Interpolation Strategy

ERA5 grid: regular lat-lon 0.25° on 37 pressure levels
- **Horizontal:** Bilinear interpolation (fast, sufficient for wind fields over smooth terrain)
- **Vertical:** Linear in log-pressure coordinates (physical for atmospheric processes)
- **Temporal:** Linear between 6-hourly analysis times
- Use `scipy.interpolate.RegularGridInterpolator` with pre-computed grid for speed

### 8.3 Moisture Uptake Model

When a particle is in the PBL (z < BLH):
```
Δq_uptake = E(x, y, t) × Δt × g / Δp
```
where:
- E = surface evaporation flux (kg m⁻² s⁻¹, positive upward)
- g = gravitational acceleration (9.81 m s⁻²)
- Δp = pressure thickness of PBL layer

The moisture is attributed to the basin at (x, y) with weight proportional to Δq_uptake.

### 8.4 Validation Checks

1. **Trajectory sanity check:** Particles should show known transport patterns (Easterly trade winds → Andes orographic lift)
2. **Moisture conservation:** Sum of attributed evaporation should not exceed column water vapor
3. **Time-of-displacement:** Should match literature values (~2–5 days Amazon → Andes)
4. **Seasonal pattern:** Should show stronger transport in wet season (Apr–Nov) vs dry season (Dec–Mar)

### 8.5 Performance Considerations

- **Dask chunking:** Process ERA5 data in monthly chunks, not all-at-once
- **Vectorization:** Compute all particles for one release time simultaneously using numpy
- **Pre-computation:** Build KD-tree for HydroBASINS spatial join once
- **Caching:** Cache interpolated wind fields for each 6-hourly time step
- **Parallelization:** `multiprocessing` over release times (embarrassingly parallel)

---

## 9. Dependencies

```
xarray>=2023.0
dask>=2023.0
cdsapi>=0.6
metpy>=1.5
cartopy>=0.21
geopandas>=0.14
rasterio>=1.3
scipy>=1.10
numpy>=1.24
plotly>=5.14
streamlit>=1.28
netCDF4>=1.6
cfgrib>=0.9      # optional, for GRIB direct read
pyarrow>=12.0    # for parquet outputs
```

---

## 10. References & Prior Art

1. **van der Ent et al. (2010)** — WAM-2layers moisture tracking. *J. Hydrometeorology*
2. **Drumond et al. (2014)** — Lagrangian moisture source diagnosis for South America. *J. Climate*
3. **Arias et al. (2015)** — Moisture sources for Colombian precipitation. *Climate Dynamics*
4. **Sprenger & Wernli (2015)** — LAGRANTO Lagrangian analysis tool. *Geosci. Model Dev.*
5. **Stohl et al. (2005)** — FLEXPART particle dispersion model. *Atmos. Chem. Phys.*
6. **Gimeno et al. (2012)** — Oceanic and terrestrial sources of continental precipitation. *Rev. Geophys.*
7. **Laverde-Barajas et al. (2019)** — Object-based rainfall analysis. In: *Spatiotemporal Analysis of Extreme Hydrological Events*, Elsevier.

---

## 11. ORBITA Interactive Basin-Click Trajectory Platform

The browser platform is named **ORBITA – Orinoquia–Andes Basin Integrated Trajectory Analysis**.

Tagline: **Tracing the pathways of atmospheric water**.

ORBITA is designed to explore and quantify moisture transport pathways (“flying rivers”) across the Orinoquia–Andes region.

A browser platform has been added to inspect the trajectory ensemble:

```text
results/trajectory_platform/index.html
```

Local/Tailscale serving is done from the `results/` folder; the root index is:

```text
results/index.html
```

### Interaction design

1. Click or select a **HydroBASINS Level 6** basin.
2. Use the month slider to navigate month by month.
3. Use the arrival-day slider and previous-days / optional days-after sliders to define the analysis window.
4. The platform filters trajectories whose `hour_back = 0` arrival point is inside the selected basin.
5. It draws:
   - all individual trajectories as very thin pale lines;
   - arrows showing the physical direction from older/source positions toward the arrival basin;
   - an agreement-weighted mean trajectory on top;
   - thicker mean segments where many trajectories are close together;
   - thinner mean segments where paths diverge or where few trajectories agree.

There is no target-city selector in the final interaction. The current Bogotá/Manizales rows are only prototype arrival basins until all-basin production trajectories are generated.

### Interface tabs

1. **Map Explorer** — main interactive visualization, basin selection, trajectory arrows, and live controls.
2. **Time Analysis** — seasonal/monthly interpretation and day-window controls.
3. **Statistics** — moisture volume in m³, relative contribution in %, path agreement, and uncertainty notes.
4. **Methods** — HydroBASINS L6, Lagrangian particle tracking, ERA5 forcing, moisture transport estimation, temporal aggregation, and limitations.

### Agreement weighting

For each backward travel time, compute the mean position of all retained trajectories and their radial dispersion around that mean:

```text
agreement_score = n_trajectories_at_hour / (1 + dispersion_km / 25)
line_width = clamp(2 + 3 × agreement_score, 2, 11)
```

### Evaporation contribution safeguard

The platform only labels a basin chart as true transported-volume contribution when production trajectories contain real physical columns such as `transport_volume_m3`, `uptake_volume_m3`, `uptake_kg`, or `evap_kg`. Until then, it explicitly labels the chart as a path-contact proxy and the absolute m³ metric as pending.

The full schema expected by the platform is:

```text
trajectory_id, release_time_utc, release_date, month,
arrival_HYBAS_ID, hour_back, lat, lon, pressure_hpa,
HYBAS_ID, MAIN_BAS,
transport_volume_m3 or uptake_volume_m3,
uptake_kg or evap_kg,
q_kgkg, pbl_flag, source_class
```

---

## 12. Next Steps (Immediate Actions)

1. Finish the 2023 ERA5 sequential download and verify all monthly files.
2. Replace prototype 2D trajectories with the full 3D/RK4 all-basin production run.
3. Add PBL-aware evaporation uptake, transported-volume estimates in m³, and basin-level moisture accounting.
4. Generate monthly and 12-month contribution summaries for each HydroBASINS L6 basin.
5. Promote the platform from path-contact proxy mode to physical transported-volume/contribution mode.

---

*This document is a living design. Sections will be updated as methodology is refined and results are obtained.*
