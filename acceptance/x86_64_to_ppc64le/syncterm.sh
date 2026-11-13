#!/bin/bash
# Acceptance test of syncterm: the build left a syncterm whose libraries all
# resolve (it has no tests). It runs without network on what build.sh left in
# $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit status
# 0.
set -euo pipefail
src=$BENCH_SRC_DIR/syncterm-1.9-src
bin=$(find "$src/build" -name syncterm -type f -perm -u+x | head -1)
[ -n "$bin" ] || { echo "error: the build left no syncterm"; exit 1; }
! ldd "$bin" | grep "not found"
echo "PASS syncterm ($bin)"
