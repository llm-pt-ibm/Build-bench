#!/bin/bash
# Acceptance test of noise-suppression-for-voice: the plugins are built and
# their libraries resolve. It runs without network on what build.sh left in
# $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit status
# 0.
set -euo pipefail
src=$BENCH_SRC_DIR/noise-suppression-for-voice
found=$(find "$src" -path "$src/build/*rnnoise_ladspa*.so" -type f | sort)
[ -n "$found" ] || { echo "error: the build left no LADSPA plugin"; exit 1; }
for f in $found; do
  if ldd "$f" | grep "not found"; then echo "FAIL: $f has unresolved libraries"; exit 1; fi
  echo "ok: $f"
done
