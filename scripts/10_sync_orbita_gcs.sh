#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-rs-weather-data}"
BUCKET="${BUCKET:-rs-weather-data-orbit}"
LOCATION="${LOCATION:-us-central1}"
ROOT="${ROOT:-/Users/gac/research_projects/atmospheric_rivers_orinoquia}"
ERA5_ROOT="${ERA5_ROOT:-/Volumes/GC_SDD1/ncdata/era5_sa}"
GS="gs://${BUCKET}"

usage() {
  cat <<EOF
Usage: $0 <command>

Commands:
  ensure-bucket      Create ${GS} if missing, with uniform bucket-level access.
  public-platform    Grant public read only for ${GS}/platform/orbita/** browser assets.
  sync-platform      Sync static ORBITA platform assets to ${GS}/platform/orbita/
  sync-processed     Sync processed trajectory summaries/assets to GCS (no raw ERA5).
  sync-era5-raw      Sync canonical raw ERA5 NetCDF archive from external disk to GCS.
  inventory          Write a local and cloud inventory manifest.

Environment overrides:
  PROJECT_ID=${PROJECT_ID}
  BUCKET=${BUCKET}
  LOCATION=${LOCATION}
  ROOT=${ROOT}
  ERA5_ROOT=${ERA5_ROOT}
EOF
}

require_gsutil() {
  command -v gsutil >/dev/null || { echo "gsutil not found" >&2; exit 1; }
}

ensure_bucket() {
  require_gsutil
  if gsutil ls -b "${GS}" >/dev/null 2>&1; then
    echo "Bucket exists: ${GS}"
  else
    echo "Creating bucket: ${GS} in project ${PROJECT_ID}, location ${LOCATION}"
    gsutil mb -p "${PROJECT_ID}" -l "${LOCATION}" -b on "${GS}"
  fi
  gsutil uniformbucketlevelaccess set on "${GS}" >/dev/null
}

public_platform() {
  ensure_bucket
  command -v gcloud >/dev/null || { echo "gcloud not found" >&2; exit 1; }
  # Keep raw ERA5/private compute products protected. Only compact browser-facing
  # files under platform/orbita/ are public so Firebase/static browsers can read them.
  gcloud storage buckets add-iam-policy-binding "${GS}" \
    --member="allUsers" \
    --role="roles/storage.objectViewer" \
    --condition="expression=resource.name.startsWith('projects/_/buckets/${BUCKET}/objects/platform/orbita/'),title=public-orbita-platform,description=Public read for compact ORBITA browser assets only" \
    --project="${PROJECT_ID}"
}

sync_platform() {
  ensure_bucket
  gsutil -m rsync -r "${ROOT}/results/trajectory_platform" "${GS}/platform/orbita"
  gsutil -m rsync -x '(^|.*/)(tables/.*\.(csv|parquet)|.*\.tmp|.*\.log)$' \
    -r "${ROOT}/results" "${GS}/processed/results_index"
}

sync_processed() {
  ensure_bucket
  gsutil -m rsync -r "${ROOT}/results/trajectory_platform/assets" "${GS}/platform/orbita/assets"
  gsutil -m cp -n "${ROOT}"/results/tables/*summary.json "${GS}/trajectories/prototype_2d_rk4/summaries/" || true
  gsutil -m cp -n "${ROOT}"/results/tables/*.parquet "${GS}/trajectories/prototype_2d_rk4/flat/" || true
}

sync_era5_raw() {
  ensure_bucket
  test -d "${ERA5_ROOT}" || { echo "Missing ERA5 root: ${ERA5_ROOT}" >&2; exit 1; }
  # rsync compares size/checksum and avoids uploading unchanged canonical files.
  gsutil -m rsync -r "${ERA5_ROOT}/pressure_levels" "${GS}/raw/era5/south_america/pressure_levels"
  gsutil -m rsync -r "${ERA5_ROOT}/surface" "${GS}/raw/era5/south_america/surface"
  if [[ -f "${ERA5_ROOT}/manifest.json" ]]; then
    gsutil cp "${ERA5_ROOT}/manifest.json" "${GS}/manifests/era5_inventory.json"
  fi
}

inventory() {
  ensure_bucket
  mkdir -p "${ROOT}/results/manifests"
  {
    echo "# ORBITA local inventory"
    date -u +"generated_utc=%Y-%m-%dT%H:%M:%SZ"
    echo "root=${ROOT}"
    echo "era5_root=${ERA5_ROOT}"
    echo
    echo "## local project files"
    find "${ROOT}/config" "${ROOT}/docs" "${ROOT}/scripts" "${ROOT}/results/trajectory_platform" -type f -maxdepth 5 -print 2>/dev/null | sort
    echo
    echo "## local ERA5 files"
    find "${ERA5_ROOT}" -type f \( -name '*.nc' -o -name 'manifest.json' \) -print 2>/dev/null | sort
  } > "${ROOT}/results/manifests/local_inventory.txt"
  gsutil cp "${ROOT}/results/manifests/local_inventory.txt" "${GS}/manifests/local_inventory.txt"
  gsutil ls -r "${GS}/**" > "${ROOT}/results/manifests/gcs_inventory.txt" || true
  echo "Wrote ${ROOT}/results/manifests/local_inventory.txt"
  echo "Wrote ${ROOT}/results/manifests/gcs_inventory.txt"
}

cmd="${1:-}"
case "${cmd}" in
  ensure-bucket) ensure_bucket ;;
  public-platform) public_platform ;;
  sync-platform) sync_platform ;;
  sync-processed) sync_processed ;;
  sync-era5-raw) sync_era5_raw ;;
  inventory) inventory ;;
  -h|--help|help|"") usage ;;
  *) echo "Unknown command: ${cmd}" >&2; usage; exit 2 ;;
esac
