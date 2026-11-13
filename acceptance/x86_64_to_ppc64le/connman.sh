#!/bin/bash
# Acceptance test of connman: the project's unit tests (make check), and the
# connmand daemon. It runs without network on what build.sh left in
# $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit status
# 0.
set -euo pipefail
src=$BENCH_SRC_DIR/connman
[ -x "$src/src/connmand" ] || { echo "error: the build left no connmand"; exit 1; }
make -C "$src" -j "$BENCH_JOBS" check
