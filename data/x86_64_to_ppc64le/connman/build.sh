#!/bin/bash
# Build recipe for connman, as it builds on x86_64: configure with the nftables
# firewall and the plugins the distribution enables, and make. It runs from the
# case directory in the environment envs/c-power9, with $BENCH_CACHE_DIR (this
# run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs) and
# $BENCH_JOBS.
set -euo pipefail
cd connman
[ -x configure ] || autoreconf -fi
./configure --with-firewall=nftables --enable-tist --enable-test --enable-loopback --enable-ethernet --enable-wifi
make -j "$BENCH_JOBS"
