#!/bin/bash
# Build recipe for rtlsdr-airband, as it builds on x86_64: the project's CMake
# build with its defaults, in the directory of its release archive (where it
# reads its version). It runs from the case directory in the environment
# envs/c-power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd RTLSDR-Airband-6.2.0
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$BENCH_JOBS"
