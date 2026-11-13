#!/bin/bash
# Build recipe for clanlib, as it builds on x86_64: autoreconf, configure and
# make, as the distribution configures it (without the documentation). It runs
# from the case directory in the environment envs/gui-power9, with
# $BENCH_CACHE_DIR (this run's build state), $BENCH_SHARED_CACHE_DIR (caches
# kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd ClanLib
autoreconf -fiv
./configure --with-pic --disable-static
make -j "$BENCH_JOBS"
