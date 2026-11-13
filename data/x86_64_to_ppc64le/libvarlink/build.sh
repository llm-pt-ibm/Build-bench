#!/bin/bash
# Build recipe for libvarlink, as it builds on x86_64: Meson. It runs from the
# case directory in the environment envs/c-power9, with $BENCH_CACHE_DIR (this
# run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs) and
# $BENCH_JOBS.
set -euo pipefail
cd libvarlink
meson setup build --buildtype=release
meson compile -C build -j "$BENCH_JOBS"
