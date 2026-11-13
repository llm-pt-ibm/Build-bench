#!/bin/bash
# Build recipe for bash-completion-doc, as it builds on x86_64: configure and
# make. It runs from the case directory in the environment envs/c-power9, with
# $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR (caches
# kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd bash-completion
[ -x configure ] || autoreconf -fi
./configure
make -j "$BENCH_JOBS"
