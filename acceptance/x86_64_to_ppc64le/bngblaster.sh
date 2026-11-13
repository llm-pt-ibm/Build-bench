#!/bin/bash
# Acceptance test of bngblaster: the project's unit tests (CTest), and the
# bngblaster binary. It runs without network on what build.sh left in
# $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit status
# 0.
set -euo pipefail
src=$BENCH_SRC_DIR/bngblaster
[ -x "$src/build/code/bngblaster/bngblaster" ] || { echo "error: the build left no bngblaster"; exit 1; }
ctest --test-dir "$src/build" --output-on-failure --no-tests=error -j "$BENCH_JOBS"
