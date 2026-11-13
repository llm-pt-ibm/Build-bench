#!/bin/bash
# Acceptance test of librealsense: the library and its tools are built and
# their libraries resolve (they need a camera to run). It runs without network
# on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and
# passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/librealsense
found=$(find "$src" -path "$src/build/*librealsense2.so*" -type f | sort)
[ -n "$found" ] || { echo "error: the build left no librealsense2 library"; exit 1; }
for f in $found; do
  if ldd "$f" | grep "not found"; then echo "FAIL: $f has unresolved libraries"; exit 1; fi
  echo "ok: $f"
done
found=$(find "$src" -path "$src/build/*rs-enumerate-devices" -type f | sort)
[ -n "$found" ] || { echo "error: the build left no rs-enumerate-devices"; exit 1; }
for f in $found; do
  if ldd "$f" | grep "not found"; then echo "FAIL: $f has unresolved libraries"; exit 1; fi
  echo "ok: $f"
done
