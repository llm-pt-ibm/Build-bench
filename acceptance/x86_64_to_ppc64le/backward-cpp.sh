#!/bin/bash
# Acceptance test of backward-cpp: the project's tests (CTest). It runs without
# network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch
# space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/backward-cpp
ctest --test-dir "$src/build" --output-on-failure --no-tests=error -j "$BENCH_JOBS"
