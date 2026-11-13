#!/bin/bash
# Acceptance test of steampipe: steampipe runs. It runs without network on what
# build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes
# with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/steampipe
bin=$src/steampipe
[ -x "$bin" ] || { echo "error: the build left no steampipe"; exit 1; }
"$bin" --version
