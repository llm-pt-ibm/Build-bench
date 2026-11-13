#!/bin/bash
# Build recipe for bngblaster, as it builds on x86_64: CMake with the unit
# tests (cmocka). It runs from the case directory in the environment
# envs/c-power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd bngblaster
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBNGBLASTER_TESTS=ON
cmake --build build --parallel "$BENCH_JOBS"
