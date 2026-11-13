#!/bin/bash
# Acceptance test of dealii: the library's quick tests (CTest), which build and
# run small programs against it. It runs without network on what build.sh left
# in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit
# status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/dealii
ctest --test-dir "$src/build" --output-on-failure --no-tests=error -j 8
