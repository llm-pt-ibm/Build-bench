#!/bin/bash
# Build recipe for noise-suppression-for-voice, as it builds on x86_64: the
# project's CMake build. It runs from the case directory in the environment
# envs/gui-power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd noise-suppression-for-voice
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$BENCH_JOBS"
