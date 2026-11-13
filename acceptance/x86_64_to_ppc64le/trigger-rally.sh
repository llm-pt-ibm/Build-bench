#!/bin/bash
# Acceptance test of trigger-rally: the game's program is built and its
# libraries resolve (it needs a display to run). It runs without network on
# what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and
# passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/trigger-rally
found=$(find "$src" -path "$src/bin/trigger-rally" -type f | sort)
[ -n "$found" ] || { echo "error: the build left no trigger-rally program"; exit 1; }
for f in $found; do
  if ldd "$f" | grep "not found"; then echo "FAIL: $f has unresolved libraries"; exit 1; fi
  echo "ok: $f"
done
