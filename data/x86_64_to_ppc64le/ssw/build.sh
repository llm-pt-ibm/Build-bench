#!/bin/bash
# Build recipe for ssw, as it builds on x86_64: the Makefile in src/ (ssw_test,
# the library and the examples). It runs from the case directory in the
# environment envs/tools-power9, with $BENCH_JOBS parallel jobs.
set -euo pipefail
cd ssw/src
make -j "$BENCH_JOBS"
