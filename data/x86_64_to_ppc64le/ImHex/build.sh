#!/bin/bash
# Build recipe for ImHex, as it builds on x86_64: CMake for an offline build
# with the patterns of ../patterns, as the distribution builds it. It runs from
# the case directory in the environment envs/gui-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd ImHex
echo 1.38.1 > VERSION
ln -sfn ../patterns ImHex-Patterns
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DIMHEX_OFFLINE_BUILD=ON -DUSE_SYSTEM_NLOHMANN_JSON=ON -DUSE_SYSTEM_CURL=ON
cmake --build build --parallel "$BENCH_JOBS"
