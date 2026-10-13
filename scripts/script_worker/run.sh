#!/bin/bash
# Run the recipe (build.sh) of a build-recipe case on this host: set up the
# build environment the case declares, then run build.sh from the package root.
# Usage: scripts/script_worker/run.sh <source_dir> [environment_script]
# The exit status is that of build.sh (2 if the environment cannot be set up).
set -uo pipefail
src=$1
env_script=${2:-}
if [ -n "$env_script" ]; then
  echo "=== build environment: $(basename "$env_script" .sh)"
  # shellcheck disable=SC1090
  source "$env_script" || { echo "error: the build environment could not be set up"; exit 2; }
fi
echo "=== build host: $(uname -m), $(nproc) cpus, ${BENCH_JOBS:-?} jobs"
echo "=== running build.sh"
cd "$src" && exec bash ./build.sh
