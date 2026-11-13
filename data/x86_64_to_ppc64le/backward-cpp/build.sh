#!/bin/bash
# Build recipe for backward-cpp, as it builds on x86_64: CMake with the tests.
# It runs from the case directory in the environment envs/c-power9, with
# $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR (caches
# kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd backward-cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DBACKWARD_TESTS=ON
cmake --build build --parallel "$BENCH_JOBS"
