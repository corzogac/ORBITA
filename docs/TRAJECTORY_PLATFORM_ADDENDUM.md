# ORBITA Platform Addendum: HydroBASINS L6 Basin-Arrival Flying-River Viewer

**ORBITA – Orinoquia–Andes Basin Integrated Trajectory Analysis** is an interactive hydro-atmospheric platform for exploring flying-river pathways across the Orinoquia–Andes region.

Tagline: **Tracing the pathways of atmospheric water**.

The current interaction is basin-first: the user selects a HydroBASINS Level 6 basin and inspects trajectories that arrive in that basin during a configurable time window.

## User interaction

1. Click or select a **HydroBASINS Level 6** basin.
2. Use the **month slider** to navigate month by month.
3. Use the **arrival-day slider** inside the selected month.
4. Use the **previous-days slider** to define how many earlier days are included in the trajectory search.
5. Optionally use the **days-after slider** to include a short post-arrival window.
6. The platform filters trajectories whose `hour_back = 0` arrival point is inside the selected basin.
7. It draws:
   - all individual trajectories as very thin pale lines;
   - arrows showing direction from older source positions toward the arrival basin;
   - an agreement-weighted mean trajectory on top;
   - charts of travel-time agreement and source/neighbour contribution along the path.

There is no target-city selector in the main interaction. Bogotá/Manizales only remain as the current prototype's available arrival basins until all-basin production trajectories are generated.

## Interface tabs

1. **Map Explorer** — main basin selection and trajectory visualization.
2. **Time Analysis** — monthly and day-window interpretation.
3. **Statistics** — transported moisture volume, relative contribution, agreement and uncertainty.
4. **Methods** — basin definition, trajectory computation, ERA5 data, moisture transport estimation, temporal aggregation, and limitations.

## Basin names and labels

HydroBASINS does not provide local river/basin names in the core shapefile. Until a naming crosswalk is added, the platform displays a clear technical name:

```text
HydroBASINS L6 <HYBAS_ID> | Pfaf <PFAF_ID> | <SUB_AREA> km²
```

A future enhancement can join IDEAM/HydroRIVERS/toponym names to these L6 units.

## Agreement thickness definition

For each backward travel time `hour_back`, compute the centroid of all retained trajectory points:

```text
mean_lon(hour), mean_lat(hour)
```

Then compute mean radial dispersion in km around that centroid. The display weight is:

```text
agreement_score = n_trajectories_at_hour / (1 + dispersion_km / 25)
line_width = clamp(2 + 3 × agreement_score, 2, 11)
```

Thick lines indicate a coherent corridor; thin lines indicate high dispersion or weak agreement.

## Direction convention

Trajectory rows are back-trajectories, so larger `hour_back` values are older/source positions and `hour_back = 0` is the arrival basin. The platform draws paths and arrows in the physical transport direction:

```text
source / older position  →  arrival basin
```

## Transported volume and contribution

The production trajectory engine should add one row per trajectory step with at least:

```text
trajectory_id, release_time_utc, release_date, month,
arrival_HYBAS_ID, hour_back, lat, lon, pressure_hpa,
HYBAS_ID, MAIN_BAS,
transport_volume_m3 or uptake_volume_m3,
uptake_kg or evap_kg,
q_kgkg, pbl_flag, source_class
```

For a selected basin and time window:

```text
absolute_volume_m3 = mean_or_sum(transport_volume_m3 for selected arrivals)
relative_contribution_i = sum(volume_m3 where path basin = i) / sum(volume_m3 over all retained path steps)
```

Until `transport_volume_m3` / `uptake_volume_m3` exists, the platform intentionally labels the chart as a path-contact proxy and the absolute m³ metric as pending.

## Current prototype

Created at:

```text
results/trajectory_platform/index.html
```

Assets:

```text
results/trajectory_platform/assets/orinoco_l6_basins_simplified.geojson
results/trajectory_platform/assets/trajectories_platform_current.csv
results/trajectory_platform/assets/arrival_basin_options.csv
results/trajectory_platform/assets/platform_metadata.json
```

Current data source is the January 2023 2D fixed-pressure RK4 trajectory ensemble. It validates the interface, L6 basin tagging, arrival-basin filtering, arrows, and day-window logic. Full scientific interpretation begins after the 3D RK4/moisture-volume engine emits production all-basin trajectories.
