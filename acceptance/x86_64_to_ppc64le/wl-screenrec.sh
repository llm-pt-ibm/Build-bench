#!/bin/bash
# Acceptance test of wl-screenrec: wl-screenrec runs. It runs without network
# on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and
# passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/wl-screenrec
bin=$src/target/release/wl-screenrec
[ -x "$bin" ] || { echo "error: the build left no wl-screenrec"; exit 1; }
"$bin" --help
