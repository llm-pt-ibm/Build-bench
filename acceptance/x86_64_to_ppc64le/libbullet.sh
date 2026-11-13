#!/bin/bash
# Acceptance test of libbullet: the project's unit tests (CTest). It runs
# without network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR:
# scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/bullet3
ctest --test-dir "$src/build" --output-on-failure --no-tests=error -j "$BENCH_JOBS"
