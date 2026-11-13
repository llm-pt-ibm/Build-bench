#!/bin/bash
# Acceptance test of qcoan: the project's test programs run. It runs without
# network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch
# space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/coan
cd "$src/build"
for t in test_aux test_charset test_symtab; do
  [ -x "$t" ] || { echo "error: the build left no $t"; exit 1; }
  ./"$t" > "$BENCH_CACHE_DIR/$t.log" 2>&1 || { cat "$BENCH_CACHE_DIR/$t.log"; echo "FAIL: $t"; exit 1; }
done
[ -x main ] || { echo "error: the build left no main"; exit 1; }
echo "PASS qcoan"
