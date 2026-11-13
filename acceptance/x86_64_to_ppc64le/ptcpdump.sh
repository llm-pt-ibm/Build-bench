#!/bin/bash
# Acceptance test of ptcpdump: ptcpdump runs. It runs without network on what
# build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes
# with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/ptcpdump
bin=$src/ptcpdump
[ -x "$bin" ] || { echo "error: the build left no ptcpdump"; exit 1; }
"$bin" --version
