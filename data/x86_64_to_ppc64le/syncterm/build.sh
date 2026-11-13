#!/bin/bash
# Build recipe for syncterm, as it builds on x86_64: CMake without cryptlib, as
# the distribution builds it. It runs from the case directory in the
# environment envs/c-power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd syncterm-1.9-src
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DWITHOUT_CRYPTLIB=ON
cmake --build build --parallel "$BENCH_JOBS"
