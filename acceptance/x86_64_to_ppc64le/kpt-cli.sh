#!/bin/bash
# Acceptance test of kpt-cli: kpt runs and reports its version. It runs without
# network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch
# space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/kpt
bin=$src/bin/kpt
[ -x "$bin" ] || { echo "error: the build left no kpt"; exit 1; }
"$bin" version
