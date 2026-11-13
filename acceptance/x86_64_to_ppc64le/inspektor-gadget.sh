#!/bin/bash
# Acceptance test of inspektor-gadget: its three programs run. It runs without
# network on what build.sh left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch
# space) and passes with exit status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/inspektor-gadget
bin=$src/bin/kubectl-gadget
[ -x "$bin" ] || { echo "error: the build left no kubectl-gadget"; exit 1; }
"$bin" version
bin=$src/bin/gadgetctl
[ -x "$bin" ] || { echo "error: the build left no gadgetctl"; exit 1; }
"$bin" --help
bin=$src/bin/ig
[ -x "$bin" ] || { echo "error: the build left no ig"; exit 1; }
"$bin" version
