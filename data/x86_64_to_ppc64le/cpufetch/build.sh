#!/bin/bash
# Build recipe for cpufetch, as it builds on x86_64: the project's Makefile,
# which picks the sources of the machine it runs on. It runs from the case
# directory in the environment envs/tools-power9, with $BENCH_JOBS parallel
# jobs.
set -euo pipefail
cd cpufetch
make -j "$BENCH_JOBS"
