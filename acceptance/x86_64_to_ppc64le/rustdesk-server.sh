#!/bin/bash
# Acceptance test of rustdesk-server: its two servers run. It runs without
# network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch
# space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/rustdesk-server
bin=$src/target/release/hbbs
[ -x "$bin" ] || { echo "error: the build left no hbbs"; exit 1; }
"$bin" --help
bin=$src/target/release/hbbr
[ -x "$bin" ] || { echo "error: the build left no hbbr"; exit 1; }
"$bin" --help
