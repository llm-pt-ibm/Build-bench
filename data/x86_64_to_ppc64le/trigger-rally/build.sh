#!/bin/bash
# Build recipe for trigger-rally, as it builds on x86_64: the project's
# makefile (src/). It runs from the case directory in the environment envs/gui-
# power9, with $BENCH_CACHE_DIR (this run's build state),
# $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd trigger-rally
make -C src -j "$BENCH_JOBS"
