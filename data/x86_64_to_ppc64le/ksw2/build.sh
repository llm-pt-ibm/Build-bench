#!/bin/bash
# Build recipe for ksw2, as it builds on x86_64: the project's Makefile, which
# builds ksw2-test with all the alignment kernels. It runs from the case
# directory in the environment envs/tools-power9, with $BENCH_JOBS parallel
# jobs.
set -euo pipefail
cd ksw2
make -j "$BENCH_JOBS"
