# Atmospheric Rivers Orinoquia

**Water Vapor Transport from Orinoquia to the Colombian Andes**

Back-trajectory analysis of atmospheric moisture transport from the Orinoquia basin to Bogotá and Manizales, using ERA5 reanalysis and Lagrangian particle tracking.

## Quick Start

```bash
# 1. Create environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Download HydroBASINS
python scripts/03_prepare_hydrobasins.py

# 3. Download ERA5 test data (1 month)
python scripts/01_download_era5.py --year 2023 --month 1 --test

# 4. Run back-trajectories (1 month test)
python scripts/04_run_lagrangian.py --start 2023-01-01 --end 2023-01-31

# 5. Aggregate basin contributions
python scripts/05_aggregate_basin.py

# 6. Generate 12-month contribution graphs
python scripts/06_monthly_contributions.py

# 7. Launch interactive dashboard
streamlit run scripts/08_basin_dashboard.py
```

## Project Structure

See `docs/DESIGN.md` for full methodology and implementation plan.

## Data

ERA5 data stored on external SSD: `/Volumes/GC_SDD1/ncdata/era5_sa/`

## Target Cities

- **Bogotá** (4.71°N, 74.07°W, 2640 m)
- **Manizales** (5.07°N, 75.52°W, 2150 m)
