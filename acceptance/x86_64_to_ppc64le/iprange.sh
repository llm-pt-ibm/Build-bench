#!/bin/bash
# Acceptance test of iprange: the project's tests (make check). It runs without
# network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch
# space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/iprange
make -C "$src" -j "$BENCH_JOBS" check
