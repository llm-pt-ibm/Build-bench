#!/bin/bash
# Acceptance test of kluctl: kluctl runs and reports its version. It runs
# without network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR:
# scratch space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/kluctl
bin=$src/bin/kluctl
[ -x "$bin" ] || { echo "error: the build left no kluctl"; exit 1; }
"$bin" version
