#!/bin/bash
# Acceptance test of schismtracker: the program is built and its libraries
# resolve (it needs a display to run). It runs without network on what build.sh
# left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit
# status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/schismtracker
found=$(find "$src" -path "$src/schismtracker" -type f | sort)
[ -n "$found" ] || { echo "error: the build left no schismtracker program"; exit 1; }
for f in $found; do
  if ldd "$f" | grep "not found"; then echo "FAIL: $f has unresolved libraries"; exit 1; fi
  echo "ok: $f"
done
