#!/bin/bash
# Build recipe for schismtracker, as it builds on x86_64: autoreconf, configure
# and make. It runs from the case directory in the environment envs/gui-power9,
# with $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR
# (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd schismtracker
autoreconf -fi
./configure
make -j "$BENCH_JOBS"
