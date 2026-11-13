#!/bin/bash
# Build recipe for dav2d, as it builds on x86_64: Meson with the tests and
# tools. It runs from the case directory in the environment envs/c-power9, with
# $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR (caches
# kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd dav2d
meson setup build --buildtype=release -Denable_tests=true -Denable_tools=true
meson compile -C build -j "$BENCH_JOBS"
