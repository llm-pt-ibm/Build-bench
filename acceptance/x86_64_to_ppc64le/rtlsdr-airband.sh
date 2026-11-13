#!/bin/bash
# Acceptance test of rtlsdr-airband: rtl_airband runs and reports its version.
# It runs without network on what build.sh left in $BENCH_SRC_DIR
# ($BENCH_CACHE_DIR: scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/RTLSDR-Airband-6.2.0
bin=$src/build/src/rtl_airband
[ -x "$bin" ] || { echo "error: the build left no rtl_airband"; exit 1; }
"$bin" -v | tee "$BENCH_CACHE_DIR/version.txt"
grep -q "RTLSDR-Airband version" "$BENCH_CACHE_DIR/version.txt"
echo "PASS rtlsdr-airband"
