#!/bin/bash
# Build recipe for minimap2, as it builds on x86_64: the project's Makefile. It
# runs from the case directory in the environment envs/tools-power9, with
# $BENCH_JOBS parallel jobs.
set -euo pipefail
cd minimap2
make -j "$BENCH_JOBS"
