#!/bin/bash
# Acceptance test of dav2d: the project's tests (meson test, checkasm among
# them). It runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/dav2d
meson test -C "$src/build" --print-errorlogs --num-processes "$BENCH_JOBS"
