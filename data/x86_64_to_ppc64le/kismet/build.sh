#!/bin/bash
# Build recipe for kismet, as it builds on x86_64: configure as the
# distribution configures it, then make all and the plugins. It runs from the
# case directory in the environment envs/kismet-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd kismet
[ -x configure ] || autoreconf -fi
# without lm-sensors (thermal information), which conda-forge lacks for ppc64le
./configure --disable-wifi-coconut --disable-optimization --enable-require-pcre2 --disable-lmsensors
make -j "$BENCH_JOBS" all
make -j "$BENCH_JOBS" plugins
